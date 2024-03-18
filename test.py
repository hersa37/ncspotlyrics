import dbus
import requests
import urllib.parse
import json
import time as ti

api_url = 'https://lrclib.net'

bus = dbus.SessionBus()
instances = bus.list_names()

list_instances = []

while len(list_instances) == 0:
    list_instances = [name for name in instances if 'org.mpris.MediaPlayer2.ncspot' in name]
    print(list_instances)

ncspot_instance = list_instances[0]
ncspot_proxy = bus.get_object(ncspot_instance, '/org/mpris/MediaPlayer2')
player_interface = dbus.Interface(ncspot_proxy, dbus_interface='org.freedesktop.DBus.Properties')
while True:
    metadata = player_interface.Get('org.mpris.MediaPlayer2.Player', 'Metadata')

    print(metadata)
    album = metadata['xesam:album']
    artist = metadata['xesam:artist'][0]
    title = metadata['xesam:title']
    duration = int(metadata['mpris:length']/1000000)
    response = requests.get('https://lrclib.net/api/get?'+
                            'artist_name='+urllib.parse.quote(artist)+
                            '&track_name='+urllib.parse.quote(title)+
                            '&duration='+str(duration)+
                            '&album_name='+urllib.parse.quote(album))
    response = response.json()
    if 'statusCode' in response:
        print('no lyric found')
    elif 'syncedLyrics' not in response or response['syncedLyrics'] is None:
        print(response['plainLyrics'])
    else:
        lyrics = response['syncedLyrics']
        lyrics = [tuple(lyric.split(" ", 1)) for lyric in lyrics.split(sep='\n')]
        
        timed_lyric = []
        for time, lyric in lyrics:
            minutes = float(time[1:3])
            seconds = float(time[4:9]) + (minutes * 60)
            miliseconds = int(seconds * 1000)
            timed_lyric.append({'time':miliseconds, 'lyric': lyric})
       
        offset = 1000
        # print(timed_lyric)
        for n in range(1, len(timed_lyric)):
            if title != player_interface.Get('org.mpris.MediaPlayer2.Player', 'Metadata')['xesam:title']:
                print("NO LYRICSSSS")
                break
            position = (player_interface.Get('org.mpris.MediaPlayer2.Player', 'Position') / 1000) + offset
            first_show = True
            while position >= timed_lyric[n-1]['time'] and position < timed_lyric[n]['time']:
                if first_show:
                    print(timed_lyric[n-1]['time'], timed_lyric[n-1]['lyric'])
                    first_show = False
                position = (player_interface.Get('org.mpris.MediaPlayer2.Player', 'Position') / 1000) + offset
                ti.sleep(0.5)
