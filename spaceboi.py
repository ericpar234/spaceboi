from skyfield.api import Topos, load, EarthSatellite
from datetime import datetime, timedelta
import math
import concurrent.futures
from io import BytesIO
import requests
import json
from io import BytesIO
import pytz
import hashlib
import os
import time


def calcPasses(satellite, startTime, hours, topo, minAltitude = 0):

    print("Calculating passes for %s" % sat.name)
    passes = []

    newPass = None
    is_new_pass = True

    difference = satellite - topo
    
    for hh in range(hours):
        for mm in range(60):
            t = startTime + timedelta(hours=hh, minutes=mm)
            topocentric = difference.at(t)
            alt, az, distance = topocentric.altaz()

            if alt.degrees < -0.5:
                is_new_pass = True

                if newPass != None:
                    if newPass["maxAlt"] >= minAltitude:
                      newPass["endTime"] = newPass["segments"][-1]["time"]
                      passes.append(newPass)

                    newPass = None
                    
            else:
                if is_new_pass:
                    is_new_pass = False
                    newPass = {
                            "satellite": satellite.name,
                            "startTime": t,
                            "endTime": None,
                            "maxAlt": -90,
                            "segments": []
                    }


                if math.isnan(alt.degrees) or math.isnan(az.degrees) or math.isnan(distance.km):
                    continue


                newPass["segments"].append({
                    "time": t,
                    "alt": round(alt.degrees),
                    "az": round(az.degrees),
                    "distance": round(distance.km)
                })

                if alt.degrees > newPass["maxAlt"]:
                    newPass["maxAlt"] = alt.degrees

    return passes


def formatPass(satPass, local_tz):
    passString = f"### Pass for {satPass['satellite']}\n"
    passString += f"**Start Time:** {satPass['startTime'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
    passString += f"**End Time:** {satPass['endTime'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
    passString += f"**Max Altitude:** {satPass['maxAlt']:.1f}\n\n"
    
    passString += "| Time | Altitude | Azimuth | Distance |\n"
    passString += "|------|----------|---------|----------|\n"
    
    for segment in satPass["segments"]:
        passString += f"| {segment['time'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')} | {segment['alt']} | {segment['az']} | {segment['distance']} km |\n"
    
    return passString

def fetchData(url):

    # hash the url to get a unique filename
    hsh = hashlib.md5(url.encode()).hexdigest()

    # check if directory exists
    if not os.path.exists('./tle'):
        os.makedirs('./tle')

    # check if file exists
    text_string = None

    refresh = False

    if os.path.exists(f'./tle/{hsh}.txt'):
        # check if file is older than 1 day
        if (time.time() - os.path.getmtime(f'./tle/{hsh}.txt')) > 86400:
            # file is older than 1 day, refresh
            refresh = True
            

        else:
            # file is not older than 1 day, load from file
            with open(f'./tle/{hsh}.txt', 'r') as f:
                text_string = f.read()

    else:
        # file does not exist, refresh
        refresh = True

    if refresh:
         response = requests.get(url)
         text_string = response.content
         text_string = text_string.decode('utf-8')

         with open(f'./tle/{hsh}.txt', 'w') as f:
             f.write(text_string)

    return text_string

if __name__ == "__main__":
    
  ts = load.timescale()
  t = ts.now()
  
  i, refreshed, sat_list = 0, False, []

  config  = None
  with open('config.json', 'r') as f:
    config = json.load(f)
    print(config.keys())

  my_topo = Topos(config["lat"], config["lon"])

  satellites = []
  for url in config["urls"]:
    # Get the json data from the URL

    text_string = fetchData(url)

    print(text_string)

    json_sats = json.loads(text_string)

    for sat in json_sats:
        # Check not already appended
        # TODO Fix this
        esat = EarthSatellite.from_omm(ts, sat)

        # search for esat.name in satellites

        if esat.name not in [sat.name for sat in satellites]:
         satellites.append(EarthSatellite.from_omm(ts, sat))
         print(satellites[-1].name)

  print("Total satellites: %d" % len(satellites))

  if config["filter_enabled"]:
    # Filter satellites
    filtered_sats = []
    for sat in satellites:
        if sat.name in config["satellites"]:
            filtered_sats.append(sat)

    print("Filtered satellites: %d" % len(filtered_sats))

    satellites = filtered_sats

  
  print(satellites[0].name)

  events = []
  for sat in satellites:
    events.extend(calcPasses(sat, t, config["hours"], my_topo, config["min_alt"]))

  print(events)
  print("Total events: %d" % len(events))


  # Sort by time

  events.sort(key=lambda x: x['startTime'])

  with open('output_time.md', 'w') as f:
      for event in events:
          f.write(formatPass(event, pytz.timezone('US/Eastern')))
          f.write("\n")


  events.sort(key=lambda x: x['maxAlt'], reverse=True)

  with open('output_alt.md', 'w') as f:
      for event in events:
          f.write(formatPass(event, pytz.timezone('US/Eastern')))
          f.write("\n")
