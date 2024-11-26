from datetime import datetime, timedelta
import math
import os
import time
import hashlib
import json
import requests
from io import BytesIO
import concurrent.futures

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QLineEdit, QLabel
)
from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import pytz

from skyfield.api import Topos, load, EarthSatellite

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

def plot_event(satellite, event, ts, topo, ax=None):
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


    max_alt = max(altitudes)
    start_label = "← Start " + times[0].astimezone(pytz.timezone('US/Eastern')).strftime('%H:%M')
    end_label = "← End "+ times[-1].astimezone(pytz.timezone('US/Eastern')).strftime('%H:%M')
    max_alt_index = np.argmax(altitudes)
    max_alt_label = times[max_alt_index].astimezone(pytz.timezone('US/Eastern')).strftime('%H:%M')
    
    # Annotate start time

    if max_alt_index != 0:
      ax.annotate(start_label, (azimuths[0], altitudes[0]), xytext=(3, 0), textcoords='offset points')
    
    # Annotate end time
    ax.annotate(end_label, (azimuths[-1], altitudes[-1]), xytext=(3, 0), textcoords='offset points')
    
    # Annotate max altitude time
    ax.annotate(max_alt_label, (azimuths[max_alt_index], max_alt), xytext=(3, 0), textcoords='offset points')

    # Plot location of the sat now if it is in the pass
    current_time = ts.now()

    if event["startTime"] < current_time < event["endTime"]:
            
        difference = satellite - topo
        topocentric = difference.at(current_time)
        alt, az, distance = topocentric.altaz()

        if alt.degrees > 0:
            ax.plot(np.radians(az.degrees), alt.degrees, 'ro', markersize=10)
            ax.annotate(event["satellite"], (np.radians(az.degrees), alt.degrees), xytext=(0,-5), textcoords='offset points', ha="center", va="top")

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

def plot_events(satellites, events, ts, topo, ax=None):
    """
    Plots multiple satellite pass events on a single polar plot.
    Parameters:
        events (list): List of dictionaries containing event details.
    """

    if ax is None:
      fig = plt.figure()
      ax = fig.add_subplot(111, polar=True)

    if not isinstance(events, list):
        events = [events]

    for event in events:
        sat = [sat for sat in satellites if sat.name == event["satellite"]][0]
        plot_event(sat, event, ts, topo, ax=ax)

    # Add title and legend
    ax.set_title("Satellite Passes in the Sky", va='bottom')
    ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1.05))

class SatelliteApp(QMainWindow):


    def __init__(self,ts, config):
        super().__init__()
        self.satellites = []
        self.events = []
        self.ts = ts
        self.topo = Topos(config["lat"], config["lon"])
        self.config = config



        # Main layout
        self.setWindowTitle("spaceboi")
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        # Left layout for table and buttons
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout)

        # Add table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Satellite", f"Start Time {self.config["timezone"]}", f"End Time {self.config["timezone"]}", "Max Altitude"])
        left_layout.addWidget(self.table)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)

        # Add buttons
        btn_layout = QHBoxLayout()
        
        # Add input to change min altitude
        alt_layout = QVBoxLayout()
        min_altitude_input = QLineEdit()
        min_altitude_input.setPlaceholderText(str(self.config["min_alt"]))
        min_altitude_input.textChanged.connect(self.on_min_altitude_changed)
        alt_layout.addWidget(QLabel("Min Altitude"))
        alt_layout.addWidget(min_altitude_input)
        btn_layout.addLayout(alt_layout)

        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self.refresh_data)
        btn_layout.addWidget(refresh_btn)
        left_layout.addLayout(btn_layout)

        # Right layout for plots
        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout)

        # Add Single plot
        self.single_fig, self.single_ax = plt.subplots(subplot_kw={'projection': 'polar'})
        self.single_canvas = FigureCanvas(self.single_fig)
        right_layout.addWidget(self.single_canvas)

        # Add Current Events plot
        self.fig, self.ax = plt.subplots(subplot_kw={'projection': 'polar'})
        self.canvas = FigureCanvas(self.fig)
        right_layout.addWidget(self.canvas)

        # Timer for updating plot
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_current_plot)
        self.timer.start(1000)

        self.refresh_data()

    def refresh_data(self):

        self.satellites = []
        for url in self.config["urls"]:
            text_string = fetchData(url)
            json_sats = json.loads(text_string)

            for sat in json_sats:
                # Check not already appended
                # TODO Fix this
                esat = EarthSatellite.from_omm(self.ts, sat)

                # search for esat.name in satellites

                if esat.name not in [sat.name for sat in self.satellites]:
                    self.satellites.append(EarthSatellite.from_omm(self.ts, sat))
                    print(self.satellites[-1].name)



        if self.config["filter_enabled"]:
            # Filter satellites
            filtered_sats = []

            for sat in self.satellites:
                if sat.name in self.config["satellites"]:
                    filtered_sats.append(sat)
            print("Filtered satellites: %d" % len(filtered_sats))
            self.satellites = filtered_sats

        
        for sat in self.satellites:
            self.events.extend(calcPasses(sat, self.ts.now(), self.config["hours"], self.topo, minAltitude=config["min_alt"]))

        self.events.sort(key=lambda x: x['startTime'])
        self.refresh_table()
        self.update_current_plot()

    def refresh_table(self):
        self.table.setRowCount(len(self.events))

        # Sort by time
        for i, event in enumerate(self.events):
            self.table.setItem(i, 0, QTableWidgetItem(event["satellite"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(event["startTime"].astimezone(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S'))))
            self.table.setItem(i, 2, QTableWidgetItem(str(event["endTime"].astimezone(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S'))))
            self.table.setItem(i, 3, QTableWidgetItem(f"{event['maxAlt']:.0f}"))

        # Resize the time cols to fit the content
        self.table.resizeColumnsToContents()

        # Don't let the table be edited
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

    def update_current_plot(self):
        self.ax.clear()

        events = []

        for event in self.events:
            if event["startTime"] < self.ts.now() < event["endTime"]:
                events.append(event)

        plot_events(self.satellites, events, self.ts, self.topo, self.ax)
        self.ax.title.set_text(f"Current Passes - {self.ts.now().astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')}")
        self.canvas.draw()

    def update_single_plot(self, event):
        if not event:
            return
        sat = [sat for sat in self.satellites if sat.name == event["satellite"]][0]
        self.single_ax.clear()
        plot_event(sat, event, self.ts, self.topo, ax=self.single_ax)
        self.single_ax.title.set_text(f"{event['satellite']} Pass - {event['startTime'].astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')}")
        self.single_canvas.draw()

    def on_table_selection_changed(self):
        selected_items = self.table.selectedItems()
        if selected_items:
            selected_row = selected_items[0].row()
            selected_event = self.events[selected_row]
            self.update_single_plot(selected_event)

    def on_min_altitude_changed(self, text):
        try:
            min_alt = int(text)
            self.config["min_alt"] = min_alt
        except ValueError:
            pass

if __name__ == "__main__":
    
  ts = load.timescale()
  t = ts.now()
  
  i, refreshed, sat_list = 0, False, []

  config  = None
  with open('config.json', 'r') as f:
    config = json.load(f)
    print(config.keys())
  #my_topo = Topos(config["lat"], config["lon"])

  #satellites = []
  #for url in config["urls"]:
  #  # Get the json data from the URL

  #  text_string = fetchData(url)
  #  json_sats = json.loads(text_string)

  #  for sat in json_sats:
  #      # Check not already appended
  #      # TODO Fix this
  #      esat = EarthSatellite.from_omm(ts, sat)

  #      # search for esat.name in satellites

  #      if esat.name not in [sat.name for sat in satellites]:
  #       satellites.append(EarthSatellite.from_omm(ts, sat))
  #       print(satellites[-1].name)

  #print("Total satellites: %d" % len(satellites))

  #if config["filter_enabled"]:
  #  # Filter satellites
  #  filtered_sats = []
  #  for sat in satellites:
  #      if sat.name in config["satellites"]:
  #          filtered_sats.append(sat)

  #  print("Filtered satellites: %d" % len(filtered_sats))

  #  satellites = filtered_sats

  #

  #events = []

  #time_start = time.time()
  #for sat in satellites:
  #  events.extend(calcPasses(sat, t, config["hours"], my_topo, config["min_alt"]))

  #print(f"Total passes: {len(events)} calculated in {time.time() - time_start:.2f} seconds")

  ## Sort by max altitude

  #events.sort(key=lambda x: x['maxAlt'], reverse=True)

  #with open('output_alt.md', 'w') as f:
  #    for event in events:
  #        f.write(formatPass(event, pytz.timezone('US/Eastern')))
  #        f.write("\n")

  # Sort by time

  #events.sort(key=lambda x: x['startTime'])

  #with open('output_time.md', 'w') as f:
  #    for event in events:
  #        f.write(formatPass(event, pytz.timezone('US/Eastern')))
  #        f.write("\n")

  #fig = plt.figure()
  #ax = fig.add_subplot(111, polar=True)
  #ani = FuncAnimation(fig, update_plot, fargs=(satellites, events, ts, ax), interval=1000, cache_frame_data=False)

  #plt.show()
  #plt.close(fig)


  app = QApplication(sys.argv)
  # Assuming satellites, events, ts, and my_topo are already initialized
  window = SatelliteApp(ts, config)
  window.show()
  sys.exit(app.exec_())
