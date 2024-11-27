from datetime import datetime, timedelta
import math
import os
import time
import hashlib
import json
import requests
from io import BytesIO
import concurrent.futures
import argparse

import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QLineEdit, QLabel, QListWidget, QAbstractItemView, QListWidgetItem, QCheckBox
)
from PyQt5.QtCore import ( Qt, QRunnable, QThreadPool, pyqtSlot, pyqtSignal, QObject )


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
    from datetime import timedelta
    import math

    print(f"Calculating passes for {satellite.name}")
    passes = []
    newPass = None

    difference = satellite - topo
    total_minutes = hours * 60
    time_intervals = (startTime + timedelta(seconds=30 * s) for s in range(total_minutes * 2))

    for t in time_intervals:
        topocentric = difference.at(t)
        alt, az, distance = topocentric.altaz()

        if math.isnan(alt.degrees) or alt.degrees < 0:
            if newPass:
                if newPass["maxAlt"] >= minAltitude:
                    newPass["endTime"] = newPass["segments"][-1]["time"]
                    passes.append(newPass)
                newPass = None
            continue

        if not newPass:
            newPass = {
                "satellite": satellite.name,
                "startTime": t,
                "endTime": None,
                "maxAlt": -90,
                "segments": []
            }

        newPass["segments"].append({
            "time": t,
            "alt": round(alt.degrees, 2),
            "az": round(az.degrees, 2),
            "distance": round(distance.km, 2)
        })
        newPass["maxAlt"] = max(newPass["maxAlt"], alt.degrees)

    if newPass and newPass["maxAlt"] >= minAltitude:
        newPass["endTime"] = newPass["segments"][-1]["time"]
        passes.append(newPass)

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

    satellite_dict = {sat.name: sat for sat in satellites}

    for event in events:
        sat = satellite_dict.get(event["satellite"])
        if sat:
            plot_event(sat, event, ts, topo, ax=ax)

    # Add title and legend
    ax.set_title("Satellite Passes in the Sky", va='bottom')
    ax.legend(loc='upper right', bbox_to_anchor=(1.2, 1.05))

class WorkerSignals(QObject):
    finished = pyqtSignal(dict)  # Emit list of satellites
    error = pyqtSignal(str)      # Emit error message as a string

class Worker(QRunnable):
    def __init__(self, urls, ts, config, filter_enabled):
        super().__init__()
        self.urls = urls
        self.ts = ts
        self.config = config
        self.filter_enabled = filter_enabled
        self.signals = WorkerSignals()
        self._is_running = True

    def stop(self):
        self._is_running = False

    @pyqtSlot()
    def run(self):
        try:
            filtered_satellites, satellites = fetchAllData(self.config)
            events = []
            topo = Topos(self.config["lat"], self.config["lon"])


            for sat in filtered_satellites:
                if not self._is_running:
                    return

                events.extend(
                  calcPasses(sat, self.ts.now(), self.config["hours"], topo, minAltitude=self.config["min_alt"])
                )


            events.sort(key=lambda x: x['startTime'])

            self.signals.finished.emit( {
                "satellites": satellites,
                "events": events,
                "all_sat_names": [sat.name for sat in satellites]
            })

        except Exception as e:
            self.signals.error.emit(str(e))  # Emit the error message

class SatelliteApp(QMainWindow):
    def __init__(self, ts, config):
        super().__init__()
        self.thread_pool = QThreadPool()
        self.satellites = []
        self.events = []
        self.all_sat_names = []
        self.active_workers = []
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
        self.table.setHorizontalHeaderLabels(["Satellite", f"Start Time {self.config['timezone']}", f"End Time {self.config['timezone']}", "Max Altitude"])
        left_layout.addWidget(self.table)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)


        config_layout = QHBoxLayout()
        # Add buttons
        btn_layout = QVBoxLayout()
        
        # Add input to change min altitude
        alt_layout = QHBoxLayout()
        min_altitude_input = QLineEdit()
        min_altitude_input.setPlaceholderText(str(self.config["min_alt"]))
        min_altitude_input.textChanged.connect(self.on_min_altitude_changed)
        alt_layout.addWidget(QLabel("Min Altitude"))
        alt_layout.addWidget(min_altitude_input)
        btn_layout.addLayout(alt_layout)

        hours_layout = QHBoxLayout()
        hours_input = QLineEdit()
        hours_input.setPlaceholderText(str(self.config["hours"]))
        hours_input.textChanged.connect(self.on_hours_changed)
        hours_layout.addWidget(QLabel("Hours"))
        hours_layout.addWidget(hours_input)
        btn_layout.addLayout(hours_layout)

        refresh_btn = QPushButton("Refresh Data")
        refresh_btn.clicked.connect(self.refresh_data)
        btn_layout.addWidget(refresh_btn)
        config_layout.addLayout(btn_layout)

        # Add satellite selection list with checkboxes
        sat_list_layout = QVBoxLayout()

        self.sat_list_widget = QListWidget()
        self.sat_list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.sat_list_widget.itemChanged.connect(self.on_satellite_selection_changed)

        select_sats_layout = QHBoxLayout()
        select_sats_layout.addWidget(QLabel("Select Satellites:"))

        # Checkbox
        select_sats_layout.addWidget(QLabel("Sats Filter Enabled:"))

        sat_filter_enabled = QCheckBox()
        sat_filter_enabled.setChecked(self.config["filter_enabled"])
        sat_filter_enabled.stateChanged.connect(self.on_filter_enabled_changed)
        select_sats_layout.addWidget(sat_filter_enabled)

        sat_list_layout.addLayout(select_sats_layout)
        sat_list_layout.addWidget(self.sat_list_widget)
        config_layout.addLayout(sat_list_layout)

        left_layout.addLayout(config_layout)

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

    def closeEvent(self, event):
        self.stop_all_workers()
        
        self.timer.stop()
        self.thread_pool.clear()
        event.accept()


    def refresh_data(self):

         self.stop_all_workers()
         self.table.setDisabled(True)  # Disable UI while refreshing

         worker = Worker(self.config["urls"], self.ts, self.config, self.config["filter_enabled"])
         worker.signals.finished.connect(self.on_refresh_data_finished)
         worker.signals.error.connect(self.on_refresh_data_error)

         self.active_workers.append(worker)

         self.thread_pool.start(worker)

    def on_refresh_data_finished(self, result):

        self.satellites = result["satellites"]
        self.events = result["events"]
        self.all_sat_names = result["all_sat_names"]

        self.table.setDisabled(False)  # Re-enable UI
        print("Data refreshed with %d satellites" % len(self.satellites))
        
        self.refresh_table()
        self.update_current_plot()
        self.update_sat_list()
        self.update_single_plot(None)

    def on_refresh_data_error(self, error_message):
        self.table.setDisabled(False)  # Re-enable UI even on error
        print(f"Error refreshing data: {error_message}")

    def stop_all_workers(self):
        for worker in self.active_workers:
            worker.stop()

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

        self.single_ax.clear()
        if not event:
            return

        try:
          sat = [sat for sat in self.satellites if sat.name == event["satellite"]][0]
        except IndexError:
            print(f"Satellite {event['satellite']} not found")
            print(self.satellites)
            return

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

        self.writeConfig()

    def on_hours_changed(self, text):
        try:
            hours = int(text)
            self.config["hours"] = hours
        except ValueError:
            pass

        self.writeConfig()

    def on_satellite_selection_changed(self, item):
        if item.checkState() == Qt.Checked:
            if item.text() not in self.config["satellites"]:
                self.config["satellites"].append(item.text())
        else:
            if item.text() in self.config["satellites"]:
                self.config["satellites"].remove(item.text())

        self.writeConfig()
        self.apply_satellite_filter()
        self.refresh_table()
        self.update_current_plot()

    def on_filter_enabled_changed(self, state):
        self.config["filter_enabled"] = state
        self.apply_satellite_filter()
        self.writeConfig()

    def apply_satellite_filter(self):
        if self.config["filter_enabled"]:
            self.satellites = [sat for sat in self.satellites if sat.name in self.config["satellites"]]

    def update_sat_list(self):
        
        self.all_sat_names.sort()
        self.sat_list_widget.blockSignals(True)  # Prevent triggering `itemChanged` during setup
        self.sat_list_widget.clear()
        for sat_name in self.all_sat_names:
            item = QListWidgetItem(sat_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if sat_name in self.config["satellites"] else Qt.Unchecked)
            self.sat_list_widget.addItem(item)
        self.sat_list_widget.blockSignals(False)

    def writeConfig(self):
        with open('config.json', 'w') as f:
            json.dump(self.config, f, indent=4)

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

def fetchAllData(config):
  satellites = []
  all_sats = []

  for url in config["urls"]:
    # Get the json data from the URL

    text_string = fetchData(url)
    json_sats = json.loads(text_string)



    for sat in json_sats:
        # Check not already appended
        # TODO Fix this
        esat = EarthSatellite.from_omm(ts, sat)

        # search for esat.name in satellites
        if esat.name not in [sat.name for sat in all_sats]:
          all_sats.append(EarthSatellite.from_omm(ts, sat))


  filtered_sats = all_sats

  if config["filter_enabled"]:
      filtered_sats = [sat for sat in all_sats if sat.name in config["satellites"]]

  print(f"Found {len(satellites)} satellites. Using {len(satellites)}/{len(filtered_sats)}")

  return filtered_sats, all_sats

if __name__ == "__main__":
    
  config  = None
  ts = load.timescale()
  i, refreshed, sat_list = 0, False, []

  parser = argparse.ArgumentParser(description='spaceboi')

  parser.add_argument('mode', type=str, choices=['gui', 'plot', 'cli'], default='cli', help='Mode to run the program in')
  parser.add_argument('--lat', type=float, required=False, help='Latitude of the observer')
  parser.add_argument('--lon', type=float, required=False, help='Longitude of the observer')
  parser.add_argument('--min_alt', type=int, required=False, help='Minimum altitude of the satellite')
  parser.add_argument('--hours', type=int, required=False, help='Number of hours to calculate passes')
  parser.add_argument('--satellites', type=str, nargs='+', required=False, help='Satellites to filter')
  parser.add_argument('--filter_enabled', action='store_true', help='Filter satellites')
  parser.add_argument('--timezone', type=str, required=False, help='Timezone of the observer')
  parser.add_argument('--config', type=str, required=False, help='Configuration file', default='config.json')

  parser.add_argument('--satellites', type=str, nargs='+', required=False, help='Satellites to filter')

  args = parser.parse_args()

  with open(args.config, 'r') as f:
    config = json.load(f)
    print(config.keys())

  for key, value in vars(args).items():
    if value:
      config[key] = value

  if args.mode == 'plot':
    topo = Topos(config["lat"], config["lon"])
    satellites, all_sats = fetchAllData(config)
    events = []
    for sat in satellites:
      events.extend(calcPasses(sat, t, config["hours"], topo, config["min_alt"]))

    # Sort by time

    events.sort(key=lambda x: x['startTime'])

    fig = plt.figure()
    ax = fig.add_subplot(111, polar=True)
    plot_events(satellites, events, ts, my_topo, ax=ax)
    plt.show()
    plt.close(fig)

  elif args.mode == 'gui':
    app = QApplication(sys.argv)
    # Assuming satellites, events, ts, and my_topo are already initialized
    window = SatelliteApp(ts, config)
    window.show()
    sys.exit(app.exec_())

  elif args.mode == 'cli':

    t = ts.now()
    topo = Topos(config["lat"], config["lon"])
    satellites, all_sats = fetchAllData(config)
    events = []
    for sat in satellites:
      events.extend(calcPasses(sat, t, config["hours"], topo, config["min_alt"]))

    # Sort by time

    events.sort(key=lambda x: x['startTime'])

    for event in events:
        print(formatPass(event, pytz.timezone('US/Eastern')))
