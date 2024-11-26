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
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import numpy as np


def calcPasses(satellite, startTime, hours, topo, minAltitude=0):
    from itertools import islice

    print(f"Calculating passes for {satellite.name}")
    passes = []
    newPass = None
    is_new_pass = True

    difference = satellite - topo
    total_minutes = hours * 60  # Total duration in minutes

    # Precompute time intervals
    time_intervals = (startTime + timedelta(minutes=m) for m in range(total_minutes))

    for t in time_intervals:
        topocentric = difference.at(t)
        alt, az, distance = topocentric.altaz()

        if alt.degrees < 0:
            # End the current pass if it exists
            is_new_pass = True
            if newPass:
                if newPass["maxAlt"] >= minAltitude:
                    newPass["endTime"] = newPass["segments"][-1]["time"]
                    passes.append(newPass)
                newPass = None
        else:
            if is_new_pass:
                # Start a new pass
                is_new_pass = False
                newPass = {
                    "satellite": satellite.name,
                    "startTime": t,
                    "endTime": None,
                    "maxAlt": -90,
                    "segments": []
                }

            # Skip invalid data
            if math.isnan(alt.degrees) or math.isnan(az.degrees) or math.isnan(distance.km):
                continue

            # Add segment data to the current pass
            newPass["segments"].append({
                "time": t,
                "alt": round(alt.degrees, 2),
                "az": round(az.degrees, 2),
                "distance": round(distance.km, 2)
            })

            # Update maximum altitude
            newPass["maxAlt"] = max(newPass["maxAlt"], alt.degrees)

    return passes

def formatPass(satPass, local_tz):
    passString = f"### Pass for {satPass['satellite']}\n"
    passString += f"**Start Time:** {satPass['startTime'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
    passString += f"**End Time:** {satPass['endTime'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
    passString += f"**Max Altitude:** {satPass['maxAlt']:.1f}\n\n"

    passString += f"| Time - {local_tz} | Altitude | Azimuth | Distance |\n"
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

def plot_event(satellite, event, ts, ax=None):
    """
    Plots a single satellite pass event on a polar plot.
    Parameters:
        event (dict): A dictionary containing event details.
        ax (PolarAxesSubplot, optional): Existing polar plot axis. If None, a new one will be created.
    """
    if ax is None:
        fig = plt.figure()
        ax = fig.add_subplot(111, polar=True)

    # Extract event details
    times = [s["time"] for s in event["segments"]]
    altitudes = [s["alt"] for s in event["segments"]]
    azimuths = [np.radians(s["az"]) for s in event["segments"]]

    # Plot the pass
    ax.plot(azimuths, altitudes, label=f"{event['satellite']}", marker=None)

    # Draw a cheveron to indicate the pass direction

    for i, time in enumerate(times):
       
        label = ""

        if i == 0 or i == len(times) - 1:
          if i == 0:
              label = "S"
          elif i == len(times) - 1:
              label = "E"

          label += time.astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')

        elif i == len(times) // 2:
          label = time.astimezone(pytz.timezone('US/Eastern')).strftime('%H:%M:%S')

        if label:
          ax.annotate(label, (azimuths[i], altitudes[i]), xytext=(10,0), textcoords='offset points')


    # Plot location of the sat now if it is in the pass

    current_time = ts.now()

    if event["startTime"] < current_time < event["endTime"]:
            
        difference = satellite - my_topo
        topocentric = difference.at(current_time)
        alt, az, distance = topocentric.altaz()

        if alt.degrees > 0:
            ax.plot(np.radians(az.degrees), alt.degrees, 'ro', markersize=10)
            ax.annotate(event["satellite"], (np.radians(az.degrees), alt.degrees), xytext=(10,0), textcoords='offset points')

    # Customize the plot
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    ax.set_rlim(90, 0)
    ax.set_rlabel_position(90)
    # hide axis labels
    ax.set_yticklabels([])

    # label North south east west

    ax.set_xticks(np.radians([0, 90, 180, 270]))
    ax.set_xticklabels(['N', 'E', 'S', 'W'])

def plot_events(satellites, events, ts, ax=None):
    """
    Plots multiple satellite pass events on a single polar plot.
    Parameters:
        events (list): List of dictionaries containing event details.
    """
    fig = plt.figure()

    if ax is None:
      ax = fig.add_subplot(111, polar=True)

    if not isinstance(events, list):
        events = [events]

    for event in events:
        sat = [sat for sat in satellites if sat.name == event["satellite"]][0]
        plot_event(sat, event, ts, ax=ax)

    # Add title and legend
    ax.set_title("Satellite Passes in the Sky", va='bottom')
    ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1.05))

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

  

  events = []
  for sat in satellites:
    events.extend(calcPasses(sat, t, config["hours"], my_topo, config["min_alt"]))

  print("Total events: %d" % len(events))



  # Sort by max altitude

  events.sort(key=lambda x: x['maxAlt'], reverse=True)

  with open('output_alt.md', 'w') as f:
      for event in events:
          f.write(formatPass(event, pytz.timezone('US/Eastern')))
          f.write("\n")

  # Sort by time

  events.sort(key=lambda x: x['startTime'])

  with open('output_time.md', 'w') as f:
      for event in events:
          f.write(formatPass(event, pytz.timezone('US/Eastern')))
          f.write("\n")


  def update_plot(frame, satellites, events, ts, ax):

      # Filter current events
      current_events = [
          event for event in events
          if event["startTime"] < ts.now() < event["endTime"]
      ]

      # Clear the axis
      ax.clear()
      
      
      # Plot the current events
      plot_events(satellites, current_events, ts, ax=ax)
      current_time_string = ts.now().astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')
      ax.set_title(f"Current Passes - {current_time_string}")

  #plot_events(satellites, events[:3], ts)
  #plt.show()

  fig = plt.figure()
  ax = fig.add_subplot(111, polar=True)
  ani = FuncAnimation(fig, update_plot, fargs=(satellites, events, ts, ax), interval=1000, cache_frame_data=False)

  plt.show()
