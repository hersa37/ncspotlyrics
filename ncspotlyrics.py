import sys

import dbus
from dbus.exceptions import DBusException
import requests
import urllib.parse
import sqlite3
from sqlite3 import Connection, Error
import time
import os.path

database_path = os.path.abspath("lyricsdb.db")
offset = 600

headers = {
    'User-Agent': 'ncspotlyrics v0.01 (https://github.com/hersa37/ncspotlyrics)'
}

def current_playing_metadata(player_interface : dbus.Interface) -> dict:
    raw_metadata = player_interface.Get('org.mpris.MediaPlayer2.Player', 'Metadata')

    metadata = {'album': str(raw_metadata['xesam:album']), 'artist': str(raw_metadata['xesam:artist'][0]),
                'title': str(raw_metadata['xesam:title']), 'duration': int(raw_metadata['mpris:length'] / 1000000)}
    return metadata


def connect_db(db : str) -> Connection:
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS lyrics (' +
                   'id integer PRIMARY KEY AUTOINCREMENT,' +
                   'title text NOT NULL,' +
                   'artist text NOT NULL,' +
                   'album text NOT NULL,' +
                   'duration int NOT NULL,' +
                   'isSynced int NOT NULL,' +
                   'lyrics text NOT NULL' +
                   ');')
    conn.commit()

    return conn


def add_to_db(metadata : dict) -> None:
    conn = None
    try:
        conn = connect_db(database_path)
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM lyrics WHERE title = ? AND album = ? AND artist = ? AND duration = ?",
                       (metadata['title'], metadata['album'], metadata['artist'], metadata['duration']))
        data = cursor.fetchone()
        if not data:
            cursor.execute(
                "INSERT INTO lyrics(title, artist, album, duration, isSynced, lyrics) VALUES (?, ?, ?, ?, ?, ?)",
                (metadata['title'], metadata['artist'], metadata['album'], metadata['duration'], metadata['isSynced'],
                 metadata['lyrics']))

            conn.commit()
    except Error as e:
        print(e)
    finally:
        if conn:
            conn.close()


def check_has_lyrics(result_list : list):
    for each in result_list:
        if each['syncedLyrics'] is not None or each['plainLyrics'] is not None:
            return each
    return None


def lyric_search(metadata : dict):
    print("Looking for lyrics...")
    title = metadata['title']
    song = {} 
    for n in range(len(title.split())):
        trimmed_title = title.rsplit(' ', n)[0]
        response = requests.get('https://lrclib.net/api/search?' +
                                'track_name=' + urllib.parse.quote(trimmed_title))
        response = response.json()

        artist = metadata['artist']
        potential_lyric = [result for result in response if artist.lower() in result['artistName'].lower()]
        if len(potential_lyric) == 0:
            continue

        check_song = potential_lyric[0]
        if check_song['instrumental']:
            song = check_song
            break

        check_song = check_has_lyrics(potential_lyric)
        if not check_song:
            return None
        else:
            song = check_song
            break

    if len(song) == 0:
        return None

    if song['instrumental']:
        metadata['isSynced'] = 0
        metadata['lyrics'] = 'instrumental'
        add_to_db(metadata)
        return metadata

    metadata['isSynced'] = 0 if 'syncedLyrics' not in song or song['syncedLyrics'] is None else 1
    metadata['lyrics'] = song['syncedLyrics'] if metadata['isSynced'] else song['plainLyrics']
    add_to_db(metadata)
    return metadata


def find_lyric(metadata : dict) -> dict:
    # Find in database first
    conn = None
    try:
        conn = connect_db(database_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT isSynced, lyrics FROM lyrics WHERE title = ? AND album = ? AND artist = ? AND duration = ?",
            (metadata['title'], metadata['album'], metadata['artist'], metadata['duration']))
        data = cursor.fetchone()
        if data:
            metadata['isSynced'] = data[0]
            metadata['lyrics'] = data[1]
            return metadata
    except Error as e:
        print(e)
    finally:
        if conn:
            conn.close()

    # Find in LRCLIB
    response = requests.get('https://lrclib.net/api/get?' +
                            'track_name=' + urllib.parse.quote(metadata['title']) +
                            '&album_name=' + urllib.parse.quote(metadata['album']) +
                            '&artist_name=' + urllib.parse.quote(metadata['artist']) +
                            '&duration=' + str(metadata['duration']), headers=headers)
    response = response.json()
    if 'statusCode' in response:
        result = lyric_search(metadata)
        if not result:
            metadata['notFound'] = 1
            return metadata
        return result

    if response['instrumental'] == 'True':
        metadata['isSynced'] = 0
        metadata['lyrics'] = 'instrumental'
        add_to_db(metadata)
        return metadata

    if response['plainLyrics'] is None and response['syncedLyrics'] is None:
        result = lyric_search(metadata)
        if not result:
            metadata['notFound'] = 1
            return metadata
        return result

    metadata['isSynced'] = 1 if 'syncedLyrics' in response and response['syncedLyrics'] is not None else 0
    metadata['lyrics'] = response['syncedLyrics'] if metadata['isSynced'] else response['plainLyrics']

    add_to_db(metadata)
    return metadata


def get_position(player_interface : dbus.Interface) -> int:
    return player_interface.Get('org.mpris.MediaPlayer2.Player', 'Position') / 1000


def display_lyrics(metadata : dict, player_interface : dbus.Interface):
    print("\n============", metadata['title'], "-", metadata['artist'], "============\n")
    if not metadata['isSynced']:
        print(metadata['lyrics'])
        print('-------------------------------------------------')
        while metadata['title'] == current_playing_metadata(player_interface)['title']:
            time.sleep(2)
        return

    lyrics = metadata['lyrics']
    lyrics = [tuple(line.split(' ', 1)) for line in lyrics.split(sep='\n')]

    timed_lyrics = []
    for timestamp, line in lyrics:
        minutes = float(timestamp[1:3])
        total_seconds = float(timestamp[4:9]) + (minutes * 60)
        miliseconds = int(total_seconds * 1000)
        timed_lyrics.append({'timestamp': miliseconds, 'line': line})

    position = get_position(player_interface)
    while position < timed_lyrics[-1]['timestamp'] and metadata['title'] == current_playing_metadata(player_interface)[
        'title']:
        for n in range(1, len(timed_lyrics)):
            position = get_position(player_interface)
            if metadata['title'] != current_playing_metadata(player_interface)['title']:
                return

            if n == 1 and position < timed_lyrics[0]['timestamp']:
                while metadata['title'] == current_playing_metadata(player_interface)['title'] and timed_lyrics[0][
                    'timestamp'] > get_position(player_interface):
                    time.sleep(1)
                continue

            line_first_time = True
            while timed_lyrics[n - 1]['timestamp'] <= position + offset < timed_lyrics[n]['timestamp']:
                if line_first_time:
                    print(">", timed_lyrics[n - 1]['line'])
                    line_first_time = False
                position = get_position(player_interface)

    position = get_position(player_interface)

    while position / 1000 < metadata['duration'] and metadata['title'] == current_playing_metadata(player_interface)[
        'title']:
        time.sleep(1)
    print('-------------------------------------------------')


def run_program():
    while True:
        ncspot_instance = list_instances[0]
        ncspot_proxy = bus.get_object(ncspot_instance, '/org/mpris/MediaPlayer2')
        player_interface = dbus.Interface(ncspot_proxy, dbus_interface='org.freedesktop.DBus.Properties')

        while True:
            print('\n\t\t Getting lyrics \n')
            metadata = current_playing_metadata(player_interface)
            metadata = find_lyric(metadata)
            if 'notFound' in metadata:
                print('\n__________ Lyrics not found __________\n')
                while metadata['title'] == current_playing_metadata(player_interface)['title']:
                    time.sleep(3)
                break

            display_lyrics(metadata, player_interface)


while True:
    list_instances = []
    while len(list_instances) == 0:
        bus = dbus.SessionBus()
        instances = bus.list_names()
        list_instances = [name for name in instances if 'org.mpris.MediaPlayer2.ncspot' in name]
        print("Waiting for ncspot to load....")
        time.sleep(1)

    try:
        run_program()
    except KeyboardInterrupt as kb:
        sys.exit(0)
    except DBusException:
        continue
