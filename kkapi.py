import json
from time import time, sleep
from random import randrange
from Cryptodome.Cipher import ARC4
from Cryptodome.Hash import MD5
from tqdm import tqdm
from utils.utils import create_requests_session

class KkboxAPI:
    def __init__(self, exception, kc1_key, email, password, kkid = None):
        self.exception = exception
        self.kc1_key = kc1_key.encode('ascii')

        self.s = create_requests_session()
        self.s.headers.update({
            'user-agent': 'okhttp/3.14.9'
        })

        self.kkid = kkid or '%030X' % randrange(16**32)

        self.hosts = {
            'ds': 'api-ds-http2.kkbox.com.tw',
            'login': 'api-login-http2.kkbox.com.tw',
            'ticket': 'api-ticket.kkbox.com.tw',
        }

        self.params = {
            'enc': 'u',
            'ver': '06090076',
            'os': 'android',
            'osver': '11',
            'lang': 'en',
            'ui_lang': 'en',
            'dist': '0021',
            'dist2': '0021',
            'resolution': '411x683',
            'of': 'j',
            'oenc': 'kc1',
        }

        self.login(email, password)

    def kc1_decrypt(self, data):
        cipher = ARC4.new(self.kc1_key)
        return cipher.decrypt(data).decode('utf-8')

    def api_call(self, host, path, params={}, payload=None):
        if host == 'ticket':
            payload = json.dumps(payload)

        host = self.hosts[host]
        params.update(self.params)
        params.update({'timestamp': int(time())})

        url = f'https://{host}/{path}'
        if not payload:
            r = self.s.get(url, params=params)
        else:
            r = self.s.post(url, params=params, data=payload)

        resp = json.loads(self.kc1_decrypt(r.content))
        return resp

    def login(self, email, password):
        md5 = MD5.new()
        md5.update(password.encode('utf-8'))
        password = md5.hexdigest()

        resp = self.api_call('login', 'login.php', payload={
            'uid': email,
            'passwd': password,
            'kkid': self.kkid,
            'registration_id': '',
        })

        if resp['status'] not in (3, -4):
            if resp['status'] == -1:
                raise self.exception('Email not found')
            elif resp['status'] == -2:
                raise self.exception('Incorrect password')
            raise self.exception('Login failed')
        
        self.apply_session(resp)

    def renew_session(self):
        resp = self.api_call('login', 'check.php')
        if resp['status'] != -4:
            raise self.exception('Session renewal failed')
        self.apply_session(resp)

    def apply_session(self, resp):
        self.sid = resp['sid']
        self.params['sid'] = self.sid

        self.lic_content_key = resp['lic_content_key'].encode('ascii')

        self.available_qualities = ['128k', '192k', '320k']
        if resp['high_quality']:
            self.available_qualities.append('hifi')
            self.available_qualities.append('hires')

    def get_songs(self, ids):
        resp = self.api_call('ds', 'v2/song', payload={
            'ids': ','.join(ids),
            'fields': 'artist_role,song_idx,album_photo_info,song_is_explicit,song_more_url,album_more_url,artist_more_url,genre_name,is_lyrics,audio_quality'
        })
        if resp['status']['type'] != 'OK':
            raise self.exception('Track not found')
        return resp['data']['songs']

    def get_song_lyrics(self, id):
        return self.api_call('ds', f'v1/song/{id}/lyrics')

    def get_album(self, id):
        resp = self.api_call('ds', f'v1/album/{id}')
        if resp['status']['type'] != 'OK':
            raise self.exception('Album not found')
        return resp['data']

    def get_album_more(self, raw_id):
        return self.api_call('ds', 'album_more.php', params={
            'album': raw_id
        })

    def get_artist(self, id):
        resp = self.api_call('ds', f'v3/artist/{id}')
        if resp['status']['type'] != 'OK':
            raise self.exception('Artist not found')
        return resp['data']
    
    def get_artist_albums(self, raw_id, limit, offset):
        resp = self.api_call('ds', f'v2/artist/{raw_id}/album', params={
            'limit': limit,
            'offset': offset,
        })
        if resp['status']['type'] != 'OK':
            raise self.exception('Artist not found')
        return resp['data']['album']

    def get_playlists(self, ids):
        resp = self.api_call('ds', f'v1/playlists', params={
            'playlist_ids': ','.join(ids)
        })
        if resp['status']['type'] != 'OK':
            raise self.exception('Playlist not found')
        return resp['data']['playlists']

    def search(self, query, types, limit):
        return self.api_call('ds', 'search_music.php', params={
            'sf': ','.join(types),
            'limit': limit,
            'query': query,
            'search_ranking': 'sc-A',
        })

    def get_ticket(self, song_id, play_mode = None):
        resp = self.api_call('ticket', 'v1/ticket', payload={
            'sid': self.sid,
            'song_id': song_id,
            'ver': '06090076',
            'os': 'android',
            'osver': '11',
            'kkid': self.kkid,
            'dist': '0021',
            'dist2': '0021',
            'timestamp': int(time()),
            'play_mode': play_mode,
        })

        if resp['status'] != 1:
            if resp['status'] == -1:
                self.renew_session()
                return self.get_ticket(song_id, play_mode)
            elif resp['status'] == -4:
                self.auth_device()
                return self.get_ticket(song_id, play_mode)
            elif resp['status'] == 2:
                # tbh i'm not sure if this is some rate-limiting thing
                # or if it's a bug on their slow-as-hell servers
                sleep(1)
                return self.get_ticket(song_id, play_mode)
            raise self.exception("Couldn't get track URLs")

        return resp['uris']

    def auth_device(self):
        resp = self.api_call('ds', 'active_sid.php', payload={
            'ui_lang': 'en',
            'of': 'j',
            'os': 'android',
            'enc': 'u',
            'sid': self.sid,
            'ver': '06090076',
            'kkid': self.kkid,
            'lang': 'en',
            'oenc': 'kc1',
            'osver': '11',
        })
        if resp['status'] != 1:
            raise self.exception("Couldn't auth device")

    def kkdrm_dl(self, url, path):
        # skip first 1024 bytes of track file
        resp = self.s.get(url, stream=True, headers={'range': 'bytes=1024-'})
        resp.raise_for_status()

        size = int(resp.headers['content-length'])
        bar = tqdm(total=size, unit='B', unit_scale=True)

        # drop 512 bytes of keystream
        rc4 = ARC4.new(self.lic_content_key, drop=512)

        with open(path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=4096):
                f.write(rc4.decrypt(chunk))
                bar.update(len(chunk))

        bar.close()
