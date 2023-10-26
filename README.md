# orpheusdl-kkbox
[OrpheusDL](https://github.com/yarrm80s/orpheusdl) module for downloading music from [KKBOX](https://www.kkbox.com/)

# Getting started
## Prerequisites
- [OrpheusDL](https://github.com/yarrm80s/orpheusdl), duh

## Installation
- Clone the repository from your ```orpheusdl``` directory:\
```git clone https://github.com/uhwot/orpheusdl-kkbox modules/kkbox```
- Update ```config/settings.json``` with KKBOX settings:\
```python orpheus.py```

# Configuration
## Global
```download_quality```:
| Value      | Format                                |
| ---------- | ------------------------------------- |
| "hifi"     | 24-bit FLAC with variable sample rate |
| "lossless" | 16-bit 44.1kHz FLAC                   |
| "high"     | AAC 320kbps                           |
| "medium"   | MP3 192kbps                           |
| "low"      | MP3 128kbps                           |
| "minimum"  | MP3 128kbps                           |

```main_resolution```:\
Supports any resolution within 2048px, after which it downloads the original cover size

## KKBOX
| Setting     | Description                    |
| ----------- | ------------------------------ |
| `kc1_key`   | Key used for API decryption    |
| `secret_key`| Constant used for "secret" MD5 |
| `email`     | Account email                  |
| `password`  | Account password               |