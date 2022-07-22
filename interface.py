import re
from urllib.parse import urlparse
from utils.models import *
from utils.utils import create_temp_filename
from .kkapi import KkboxAPI


module_information = ModuleInformation(
    service_name = 'KKBOX',
    module_supported_modes = ModuleModes.download | ModuleModes.lyrics | ModuleModes.covers,
    global_settings = {'kc1_key': ''},
    session_settings = {'email': '', 'password': ''},
    session_storage_variables = ['kkid'],
    netlocation_constant = 'kkbox',
    url_decoding = ManualEnum.manual,
    login_behaviour = ManualEnum.manual,
    test_url = 'https://play.kkbox.com/album/OspOC7CYqcVQY_uLAV'
)


class ModuleInterface:
    def __init__(self, module_controller: ModuleController):
        settings = module_controller.module_settings
        self.exception = module_controller.module_error
        self.tsc = module_controller.temporary_settings_controller
        self.default_cover = module_controller.orpheus_options.default_cover_options
        self.check_sub = not module_controller.orpheus_options.disable_subscription_check
        if self.default_cover.file_type is ImageFileTypeEnum.webp:
            self.default_cover.file_type = ImageFileTypeEnum.jpg

        self.session = KkboxAPI(self.exception, settings['kc1_key'], settings['email'], settings['password'], self.tsc.read('kkid'))
        self.tsc.set('kkid', self.session.kkid)

        self.quality_parse = {
            QualityEnum.MINIMUM: '128k',
            QualityEnum.LOW: '128k',
            QualityEnum.MEDIUM: '192k',
            QualityEnum.HIGH: '320k',
            QualityEnum.LOSSLESS: 'hifi',
            QualityEnum.HIFI: 'hires'
        }

        curr_quality = self.quality_parse[module_controller.orpheus_options.quality_tier]
        if self.check_sub and curr_quality not in self.session.available_qualities:
            print('KKBOX: quality set in the settings is not accessible by the current subscription')

    def custom_url_parse(self, link):
        url = urlparse(link)

        path_match = None
        if url.hostname == 'play.kkbox.com':
            path_match = re.match(r'^\/(track|album|artist|playlist)\/([a-zA-Z0-9-_]{18})', url.path)
        elif url.hostname == 'www.kkbox.com':
            path_match = re.match(r'^\/[a-z]{2}\/[a-z]{2}\/(song|album|artist|playlist)\/([a-zA-Z0-9-_]{18})', url.path)
        else:
            raise self.exception(f'Invalid URL: {link}')

        if not path_match:
            raise self.exception(f'Invalid URL: {link}')
        
        type = path_match.group(1)
        if type == 'song':
            type = 'track'

        return MediaIdentification(
            media_type = DownloadTypeEnum[type],
            media_id = path_match.group(2)
        )

    def get_track_info(self, track_id: str, quality_tier: QualityEnum, codec_options: CodecOptions, data={}, alb_info={}) -> TrackInfo:
        quality = self.quality_parse[quality_tier]
        data = data.get(track_id)
        if not data:
            data = self.session.get_songs([track_id])[0]

        tags = Tags(
            album_artist = alb_info.get('artist_name') or data['artist_name'],
            track_number = int(data['song_idx']),
            total_tracks = alb_info.get('num_tracks'),
            genres = [data['genre_name']],
            release_date = alb_info.get('album_date')
        )

        if 'mainartist_list' in data['artist_role']:
            data['artist_role']['mainartists'] = data['artist_role']['mainartist_list']['mainartist']
        if 'featuredartist_list' in data['artist_role']:
            data['artist_role']['featuredartists'] = data['artist_role']['featuredartist_list']['featuredartist']

        artists = data['artist_role']['mainartists']
        if 'featuredartists' in data['artist_role']:
            artists.extend(data['artist_role']['featuredartists'])

        if quality not in data['audio_quality']:
            quality = data['audio_quality'][-1]

        error = None
        if quality not in self.session.available_qualities:
            error = 'Quality not available by your subscription'

        codec = {
            '128k': CodecEnum.MP3,
            '192k': CodecEnum.MP3,
            '320k': CodecEnum.AAC,
            'hifi': CodecEnum.FLAC,
            'hires': CodecEnum.FLAC,
        }[quality]

        bitrate = {
            '128k': 128,
            '192k': 192,
            '320k': 320,
            'hifi': 1411,
            'hires': None,
        }[quality]

        return TrackInfo(
            name = data.get('song_name') or data['text'],
            album_id = data['album_more_url'].split('/')[-1] if not alb_info else alb_info['album_more_url'].split('/')[-1],
            album = data['album_name'] if not alb_info else alb_info['album_name'],
            artists = artists,
            tags = tags,
            codec = codec,
            cover_url = self.get_img_url(data['album_photo_info']['url_template'], self.default_cover.resolution, self.default_cover.file_type),
            release_year = int(alb_info['album_date'].split('-')[0]) if alb_info else None,
            explicit = bool(data['song_is_explicit']),
            artist_id = data['artist_more_url'].split('/')[-1] if not alb_info else alb_info['artist_more_url'].split('/')[-1],
            bit_depth = 16 if quality != 'hires' else 24,
            sample_rate = 44.1 if quality != 'hires' else None,
            bitrate = bitrate,
            download_extra_kwargs = {'id': data['song_more_url'].split('/')[-1], 'quality': quality},
            cover_extra_kwargs = {'data': data},
            lyrics_extra_kwargs = {'data': data},
            error = error
        )

    def get_track_download(self, id, quality):
        format = {
            '128k': 'mp3_128k_chromecast',
            '192k': 'mp3_192k_kkdrm1',
            '320k': 'aac_320_download_kkdrm',
            'hifi': 'flac_16_download_kkdrm',
            'hires': 'flac_24_download_kkdrm',
        }[quality]

        # used for getting DRM-free mp3 128k urls
        play_mode = None
        if format == 'mp3_128k_chromecast':
            play_mode = 'chromecast'

        url = None
        urls = self.session.get_ticket(id, play_mode)
        for fmt in urls:
            if fmt['name'] == format:
                if format == 'mp3_128k_chromecast':
                    return TrackDownloadInfo(
                        download_type = DownloadEnum.URL,
                        file_url = fmt['url'],
                    )
                url = fmt['url']
                break

        temp_path = create_temp_filename()
        self.session.kkdrm_dl(url, temp_path)

        return TrackDownloadInfo(
            download_type = DownloadEnum.TEMP_FILE_PATH,
            temp_file_path = temp_path
        )

    def get_album_info(self, album_id: str, raw_ids={}) -> Optional[AlbumInfo]:
        raw_id = raw_ids.get(album_id)
        if not raw_id:
            raw_id = self.session.get_album(album_id)['album']['album_id']

        data = self.session.get_album_more(raw_id)

        info = data['info']

        data_kwargs = {}
        song_id_list = []
        for song in data['song_list']['song']:
            id = song['song_more_url'].split('/')[-1]
            song_id_list.append(id)
            data_kwargs[id] = song
        
        info['num_tracks'] = len(song_id_list)

        return AlbumInfo(
            name = info['album_name'],
            artist = info['artist_name'],
            tracks = song_id_list,
            release_year = int(info['album_date'].split('-')[0]),
            explicit = bool(info['album_is_explicit']),
            artist_id = info['artist_more_url'].split('/')[-1],
            cover_url = self.get_img_url(info['album_photo_info']['url_template'], self.default_cover.resolution, self.default_cover.file_type),
            cover_type = self.default_cover.file_type,
            all_track_cover_jpg_url = self.get_img_url(info['album_photo_info']['url_template'], self.default_cover.resolution, ImageFileTypeEnum.jpg),
            description = info['album_descr'],
            track_extra_kwargs = {'data': data_kwargs, 'alb_info': info}
        )

    def get_playlist_info(self, playlist_id: str) -> PlaylistInfo:
        data = self.session.get_playlists([playlist_id])[0]

        data_kwargs = {}
        song_id_list = []
        for song in data['songs']:
            id = song['song_more_url'].split('/')[-1]
            song_id_list.append(id)
            data_kwargs[id] = song

        return PlaylistInfo(
            name = data['title'],
            creator = data['user']['name'] if data['user'] else None,
            tracks = song_id_list,
            release_year = int(data['created_at'].split('-')[0]),
            creator_id = data['user']['id'] if data['user'] else None,
            cover_url = self.get_img_url(data['cover_photo_info']['url_template'], self.default_cover.resolution, self.default_cover.file_type),
            cover_type = self.default_cover.file_type,
            description = data['content'],
            track_extra_kwargs = {'data': data_kwargs}
        )

    def get_artist_info(self, artist_id: str, get_credited_albums: bool, data=None) -> ArtistInfo:
        profile = data
        albums = []
        offset = 0
        if not data:
            data = self.session.get_artist(artist_id)
            profile = data['profile']
            albums = data['album']
            offset = 10

        if len(albums) == 10:
            albums.extend(self.session.get_artist_albums(profile['artist_id'], 8008135, offset))

        raw_ids = {}
        album_id_list = []
        for album in albums:
            id = album['encrypted_album_id']
            album_id_list.append(id)
            raw_ids[id] = album['album_id']

        return ArtistInfo(
            name = profile['artist_name'],
            albums = album_id_list,
            album_extra_kwargs = {'raw_ids': raw_ids},
        )

    def get_track_cover(self, track_id: str, cover_options: CoverOptions, data=None) -> CoverInfo:
        data = data or self.session.get_songs([track_id])[0]
        url_template = data['album_photo_info']['url_template']
        url = self.get_img_url(url_template, cover_options.resolution, cover_options.file_type)
        return CoverInfo(url=url, file_type=cover_options.file_type)

    def get_track_lyrics(self, track_id: str, data={}) -> LyricsInfo:
        if data.get('is_lyrics') == False or data.get('song_lyrics_valid') == 0:
            return LyricsInfo()
        resp = self.session.get_song_lyrics(track_id)
        if resp['status']['type'] != 'OK':
            return LyricsInfo()

        embedded = ''
        synced = ''
        for lyr in resp['data']['lyrics']:
            if not lyr['content']:
                embedded += '\n'
                synced += '\n'
                continue

            time = lyr['start_time']
            min = int(time / (1000 * 60))
            sec = int(time / 1000) % 60
            ms = int(time % 100)
            time_tag = f'[{min:02d}:{sec:02d}.{ms:02d}]'

            embedded += lyr['content'] + '\n'
            synced += time_tag + lyr['content'] + '\n'

        return LyricsInfo(embedded, synced)

    def search(self, query_type: DownloadTypeEnum, query: str, track_info: TrackInfo = None, limit: int = 10):
        query_type = query_type.name
        if query_type == 'track':
            query_type = 'song'

        # tfw this shitty streaming service has no way to search for ISRCs

        results = self.session.search(query, [query_type], limit)[f'{query_type}_list'][query_type]

        if query_type == 'song':
            search_results = []
            for i in results:
                artists = i['artist_role']['mainartist_list']['mainartist']
                if 'featuredartist_list' in i['artist_role']:
                    artists.extend(i['artist_role']['featuredartist_list']['featuredartist'])
            
                search_results.append(SearchResult(
                    result_id = i['song_more_url'].split('/')[-1],
                    name = i['song_name'],
                    artists = artists,
                    explicit = i['song_is_explicit'],
                    additional = [i['album_name']],
                    extra_kwargs = {'data': i}
                ))
            return search_results
        elif query_type == 'album':
            return [SearchResult(
                result_id = i['album_more_url'].split('/')[-1],
                name = i['album_name'],
                artists = [i['artist_name']],
                explicit = i['album_is_explicit'],
                extra_kwargs = {'raw_ids': {i['album_more_url'].split('/')[-1]: i['album_id']}}
            ) for i in results]
        elif query_type == 'artist':
            return [SearchResult(
                result_id = i['artist_more_url'].split('/')[-1],
                name = i['artist_name'],
                extra_kwargs = {'data': i}
            ) for i in results]
        elif query_type == 'playlist':
            return [SearchResult(
                result_id = i['id'],
                name = i['title'],
                artists = [i['user']['name']],
                additional = [i['content']]
            ) for i in results]

    def get_img_url(self, url_template, size, file_type: ImageFileTypeEnum):
        url = url_template
        # not using .format() here because of possible data leak vulnerabilities
        if size > 2048:
            url = url.replace('fit/{width}x{height}', 'original')
            url = url.replace('cropresize/{width}x{height}', 'original')
        else:
            url = url.replace('{width}', str(size))
            url = url.replace('{height}', str(size))
        url = url.replace('{format}', file_type.name)
        return url
