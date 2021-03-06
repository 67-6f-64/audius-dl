import re
import os
import sys
import json
import time
import requests
import urllib.parse
import shutil
from joblib import Parallel, delayed
from mutagen.mp4 import MP4, MP4Cover
import subprocess

import multiprocessing




def fix_filename(filename):
	return re.sub(r'[\/\*\<\?\>\|\<\>]', '-', filename)

def add_tags(filename, title, artist, description, cover):
		tags = MP4(filename + ".m4a").tags
		if description != None:
			tags["desc"] = description
		tags["\xa9nam"] = title
		tags["\xa9alb"] = "Audius"
		tags["\xa9ART"] = artist

		if cover is not None:
			tags["covr"] = [
				MP4Cover(cover[:], imageformat=MP4Cover.FORMAT_JPEG)
			]
		tags.save(filename + ".m4a")

def download_fragment(data, i, endpoint):
	global segments_arr
	print("\033[K", "Fragment: [{}/{}]".format(i + 1, len(data['data'][0]['track_segments'])), "\r", end='')
	sys.stdout.flush()
	segments_arr[i] = requests.get(f"{endpoint}/ipfs/" + data['data'][0]['track_segments'][i]['multihash']).content

def download_fragment_api(data, i, endpoint):
	global segments_arr
	print("\033[K", "Fragment: [{}/{}]".format(i + 1, len(data['data']['track_segments'])), "\r", end='')
	sys.stdout.flush()
	segments_arr[i] = requests.get(f"{endpoint}/ipfs/" + data['data']['track_segments'][i]['multihash']).content

def get_node_endpoint(track_id, endpoint):
	while(True):
		r = requests.get(f"{endpoint}/v1/full/tracks/{track_id}")
		if r.status_code == 200:
			j = json.loads(r.text)
			endpoints = (j['data']['user']['creator_node_endpoint']).split(',')
			return endpoints
		time.sleep(2)

def get_available_endpoint():
	r = requests.get('https://api.audius.co')
	j = json.loads(r.text)
	return j['data'][0]

def resolve_link(link, endpoint):
	while True:
		headers = {
			'Accept': 'text/plain'
		}
		if link[-1] == '/':
			link = link[:-1]
		r = requests.get(f'{endpoint}/v1/resolve', params = { 'url': link }, headers = headers)

		if r.status_code == 200:
			return r.text
		elif r.status_code == 404:
			print("Returned 404, can't download!")
			exit()
		else:
			time.sleep(2)

def get_permalink_for_track(id):
	r = requests.get(f'https://audius.co/tracks/{id}')
	return r.url

def get_info_from_permalink(link):
	link_array = link.split("/")
	account = link_array[3]
	track_id = (link_array[4].split("-"))[-1]

	title = urllib.parse.unquote(link_array[4])
	title = title [:-(len(track_id) + 1)]
	title = title.replace('"', '\"')
	title = urllib.parse.quote(title)
	return track_id, title, account

def download_single_track_from_permalink(link, folder_name=''):
	global segments_arr
	track_id, title, account = get_info_from_permalink(link)

	endpoint = get_available_endpoint()
	print(f"API endpoint: {endpoint}")

	headers = {
		'content-type': 'application/json;charset=UTF-8',
		'referer': link,
	}

	# Why did Boys Noize have to put " in their titles
	data = '{"tracks":[{"id":' + str(track_id) + ',"url_title":"' + str(title.replace('"', '\"')) + '","handle":"' + str(account) + '"}]}'
	r = requests.post(f'{endpoint}/tracks_including_unlisted', headers=headers, data=data)

	data = json.loads(r.text)

	print("Number of segments: {}".format(len(data['data'][0]['track_segments'])))
	segments_arr = manager.list([None] * len(data['data'][0]['track_segments']))

	r = resolve_link(link, endpoint)
	node_json = json.loads(r)

	node_endpoints = get_node_endpoint(node_json['data']['id'],endpoint)
	print(f"Node endpoints: {' / '.join(node_endpoints)}")
	selected_node_endpoint = node_endpoints[0]
	print(f"Selected node endpoint: {selected_node_endpoint}")

	Parallel(n_jobs=8)(delayed(download_fragment)(data,i, selected_node_endpoint) for i in range(len(data['data'][0]['track_segments'])))
	all_seg = b''.join(segments_arr)

	global base_path
	os.chdir(base_path)
	try:
		os.mkdir("Files")
	except:
		pass
	os.chdir('Files')

	if folder_name != '':
		folder_name = fix_filename(folder_name)
		try:
			os.mkdir(folder_name)
		except:
			pass
		os.chdir(folder_name)

	p = subprocess.Popen(["ffmpeg", "-loglevel", "panic", "-stats", "-y", "-i", "pipe:", "-c:a", "copy", f"{track_id}.m4a"], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT)
	grep_stdout = p.communicate(input=all_seg)[0]

	print("\n" + (grep_stdout.decode()).rstrip())


	cover = None
	if node_json['data']['artwork'] is None:
		cover = None
	else:
		try:
			cover = requests.get(node_json['data']['artwork']['1000x1000']).content
		except:
			cover = None
	try:
		description = data['data'][0]['description']
	except:
		description = None

	add_tags(track_id, data['data'][0]['title'], node_json['data']['user']['name'], description, cover)
	shutil.move(f"{track_id}.m4a", f"{fix_filename(data['data'][0]['title'])}.m4a")
	print("Done!")

def download_single_track_from_api(track_id, folder_name=''):
	global segments_arr

	endpoint = get_available_endpoint()
	print(f"API endpoint: {endpoint}")

	r = requests.get(f"{endpoint}/v1/full/tracks/" + track_id)
	data = json.loads(r.text)

	while(True):
		try:
			node_endpoints = get_node_endpoint(data['data']['id'], endpoint)
			break
		except:
			print("Failed to get endpoint! Trying again in five seconds!")
			time.sleep(5)
		

	print(f"Node endpoints: {' / '.join(node_endpoints)}")
	selected_node_endpoint = node_endpoints[0]
	print(f"Selected node endpoint: {selected_node_endpoint}")

	print("Number of segments: {}".format(len(data['data']['track_segments'])))
	segments_arr = manager.list([None] * len(data['data']['track_segments']))

	Parallel(n_jobs=8)(delayed(download_fragment_api)(data, i, selected_node_endpoint) for i in range(len(data['data']['track_segments'])))
	all_seg = b''.join(segments_arr)

	global base_path
	os.chdir(base_path)
	try:
		os.mkdir("Files")
	except:
		pass
	os.chdir('Files')

	if folder_name != '':
		folder_name = fix_filename(folder_name)
		try:
			os.mkdir(folder_name)
		except:
			pass
		os.chdir(folder_name)

	track_id = data['data']['id']
	p = subprocess.Popen(["ffmpeg", "-loglevel", "panic", "-stats", "-y", "-i", "pipe:", "-c:a", "copy", f"{track_id}.m4a"], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.STDOUT)
	grep_stdout = p.communicate(input=all_seg)[0]

	print("\n" + (grep_stdout.decode()).rstrip())


	cover = None
	if data['data']['artwork'] is None:
		cover = None
	else:
		try:
			cover = requests.get(data['data']['artwork']['1000x1000']).content
		except:
			cover = None

	try:
		description = data['data']['description']
	except:
		description = None

	add_tags(track_id, data['data']['title'], data['data']['user']['name'], description, cover)
	shutil.move(f"{track_id}.m4a", f"{fix_filename(data['data']['title'])}.m4a")
	print("Done!")

def download_album(link):
	endpoint = get_available_endpoint()
	print(f"API endpoint: {endpoint}")

	res = resolve_link(link, endpoint)
	j = json.loads(res)
	user_id = j['data'][0]['user']['id']
	album_id = j['data'][0]['id']
	album_name = j['data'][0]['playlist_name']

	r = requests.get(f"{endpoint}/v1/full/playlists/{album_id}?user_id={user_id}")

	j = json.loads(r.text)
	for index, t in enumerate(j['data'][0]['tracks']):
		print(f"Track [ {index + 1} / {len(j['data'][0]['tracks'])} ]")
		download_single_track_from_api(t['id'], album_name)

def download_profile(link):
	endpoint = get_available_endpoint()
	print(f"API endpoint: {endpoint}")

	res = resolve_link(link, endpoint)
	j = json.loads(res)
	user_id = j['data']['id']
	username = j['data']['handle']

	r = requests.get(f"{endpoint}/v1/users/{user_id}/tracks")
	#print(r.text)

	j = json.loads(r.text)
	
	for index, i in enumerate(j['data']):
		print(f"Track [ {index + 1} / {len(j['data'])} ]")
		download_single_track_from_api(i['id'], username)


def main():
	if len(sys.argv) != 2:
		link = input("Please enter a link: ")
	else:
		link = sys.argv[1]

	if '/album/' in link:
		download_album(link)
		exit()

	elif '/playlist/' in link:
		download_album(link)
		exit()

	if link[-1] == '/':
		link = link[:-1]

	if link.split('audius.co')[1].count('/') == 1:
		download_profile(link)
		exit()

	elif link.split('audius.co')[1].count('/') == 2:
		download_single_track_from_permalink(link)
		exit()



if __name__ == '__main__':
	base_path = os.getcwd()

	manager = multiprocessing.Manager()
	segments_arr = manager.list([None])
	main()
