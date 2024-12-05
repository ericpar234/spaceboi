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
    QVBoxLayout, QWidget, QPushButton, QHBoxLayout, QLineEdit, QLabel, QListWidget, QAbstractItemView, QListWidgetItem, QCheckBox, QSizePolicy, QHeaderView
)
from PyQt5.QtCore import ( Qt, QRunnable, QThreadPool, pyqtSlot, pyqtSignal, QObject)
from PyQt5.QtGui import QIcon


from PyQt5.QtCore import QTimer
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
import pytz
from mpl_toolkits.basemap import Basemap

from skyfield.api import Topos, load, EarthSatellite

def calcPasses(satellite, startTime, hours, topo, minAltitude=0):
    ts = load.timescale()
    endTime = startTime + timedelta(hours=hours)
    
    t0 = startTime
    t1 = startTime + timedelta(hours=hours)
    
    difference = satellite - topo
    events = satellite.find_events(topo, t0, t1, altitude_degrees=0)


    # print number of 1s in events[1]
    setCount =  np.count_nonzero(events[1] == 2)

    # Print the events ( timearray, event(which is 2 0 or 1) )
    passes = []

    riseTime = None
    setTime = None
    culmTime = None


    # If all just culmination events just return the beginning and end times, and a single segment
    if np.count_nonzero(events[1] == 1) == len(events[1]):
        newPass = {
            "satellite": satellite.name,
            "startTime": t0,
            "endTime": t1,
            "segments": []
        }

        topocenteric = difference.at(t0)
        alt, az, distance = topocenteric.altaz()
        newPass["segments"].append({
            "time": t0.utc_datetime(),
            "alt": round(alt.degrees, 2),
            "az": round(az.degrees, 2),
            "distance": round(distance.km, 2)
        })

        topocenteric = difference.at(t1)
        alt, az, distance = topocenteric.altaz()
        newPass["segments"].append({
            "time": t1.utc_datetime(),
            "alt": round(alt.degrees, 2),
            "az": round(az.degrees, 2),
            "distance": round(distance.km, 2)
        })

        newPass["maxAlt"] = round(alt.degrees, 2)

        if newPass["maxAlt"] < minAltitude:
            return []

        return [newPass]




    # print type of events data
    for i in range(0, len(events[0])):

        if events[1][i] == 0:
            riseTime = events[0][i]
        elif events[1][i] == 1:
            culmTime = events[0][i]

        elif events[1][i] == 2:
            setTime = events[0][i]

        # If the last event and we have a riseTime but no setTime, Calculate the time now
        if i == len(events[0]) - 1 and riseTime is not None and setTime is None:
            # Set time to now
            setTime = t1

        if setTime is not None:
            if riseTime is None:
                # Set time to now
                riseTime = ts.now()

            if culmTime is None:
                # Set time to now
                culmTime = ts.now()

            newPass = {
                "satellite": satellite.name,
                "startTime": riseTime,
                "endTime": setTime,
                "maxAlt": culmTime,
                "segments": []
            }

            topocenteric = difference.at(culmTime)
            alt, az, distance = topocenteric.altaz()

            if math.isnan(alt.degrees) or math.isnan(az.degrees) or math.isnan(distance.km):
                riseTime = None
                setTime = None
                culmTime = None
                continue

            if alt.degrees < minAltitude:
                riseTime = None
                setTime = None
                culmTime = None
                continue

            else:
                newPass["segments"].append({
                    "time": culmTime.utc_datetime(),
                    "alt": round(alt.degrees, 2),
                    "az": round(az.degrees, 2),
                    "distance": round(distance.km, 2)
                })
                newPass["maxAlt"] = alt.degrees

            interval_start = riseTime.utc_datetime()
            interval_end = setTime.utc_datetime()


            time_intervals = [interval_start + timedelta(seconds=30 * s)
                          for s in range(int((interval_end - interval_start).total_seconds() / 30) + 1)]
        

            for t in time_intervals:
                skyfield_time = ts.utc(t.year, t.month, t.day, t.hour, t.minute, t.second)
                topocentric = difference.at(skyfield_time)
                alt, az, distance = topocentric.altaz()
                
                if math.isnan(alt.degrees) or alt.degrees < 0:
                    continue
                
                newPass["segments"].append({
                    "time": t,
                    "alt": round(alt.degrees, 2),
                    "az": round(az.degrees, 2),
                    "distance": round(distance.km, 2)
                })


            # Sort segments by time

            newPass["segments"].sort(key=lambda x: x['time'])

            passes.append(newPass)
            riseTime = None
            setTime = None
            culmTime = None
            newPass = None
            
    print(f"{satellite.name} found {len(passes)} passes")

    return passes


def formatPass(satPass, local_tz):
    passString = f"### Pass for {satPass['satellite']}\n"
    passString += f"**Start Time:** {satPass['startTime'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
    passString += f"**End Time:** {satPass['endTime'].astimezone(local_tz).strftime('%Y-%m-%d %H:%M:%S')}\n"
    passString += f"**Max Alt:** {satPass['maxAlt']:.1f}\n\n"

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
    if max_alt_index != 0 and len(altitudes) > 2:
      ax.annotate(start_label, (azimuths[0], altitudes[0]), xytext=(3, 0), textcoords='offset points')
    
    # Annotate end time
    if len(altitudes) > 2:
        ax.annotate(end_label, (azimuths[-1], altitudes[-1]), xytext=(3, 0), textcoords='offset points')
    

    # Annotate max altitude time
    if len(altitudes) > 2:
        ax.annotate(max_alt_label, (azimuths[max_alt_index], max_alt), xytext=(3, 0), textcoords='offset points')

    # Plot location of the sat now if it is in the pass
    current_time = ts.now()

    if event["startTime"] < current_time < event["endTime"]:
            
        difference = satellite - topo
        topocentric = difference.at(current_time)
        alt, az, distance = topocentric.altaz()

        if alt.degrees > 0:
            ax.plot(np.radians(az.degrees), alt.degrees, 'ro', markersize=5)
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
            filtered_satellites, satellites = fetchAllData(self.config, self.ts)
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
                "satellites": filtered_satellites,
                "events": events,
                "all_sat_names": [sat.name for sat in satellites]
            })

        except Exception as e:
            self.signals.error.emit(str(e))  # Emit the error message


dark_stylesheet = """
    QMainWindow {
        background-color: #2b2b2b;
        color: #ffffff;
    }
    QPushButton {
        background-color: #3c3f41;
        color: #ffffff;
        border: 1px solid #555555;
        border-radius: 5px;
        padding: 5px;
    }
    QPushButton:hover {
        background-color: #444444;
    }
"""

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
        self.selected_sat = None

        self.setWindowIcon(QIcon(os.path.join( os.path.curdir, 'assets/spaceboi_small.png' )))

        #if darkdetect.isDark():
        #    self.setStyleSheet(dark_stylesheet)


        # Main layout
        self.setWindowTitle("spaceboi")
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        # Left layout for table and buttons
        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout)

        # Add map plot
        self.fig_map, self.ax_map = plt.subplots(figsize=(12, 6))
        self.canvas_map = FigureCanvas(self.fig_map)
        self.map = initialize_map(self.ax_map)
        left_layout.addWidget(self.canvas_map)
        self.fig_map.tight_layout()

        # Bottom left layout for table and buttons
        bottom_left_layout = QHBoxLayout()
        left_layout.addLayout(bottom_left_layout)


        # Add buttons
        config_layout = QVBoxLayout()

        # Add satellite selection list with checkboxes
        sat_list_layout = QVBoxLayout()

        # Add input to change min altitude
        alt_layout = QHBoxLayout()
        min_altitude_input = QLineEdit()
        min_altitude_input.setPlaceholderText(str(self.config["min_alt"]))
        min_altitude_input.textChanged.connect(self.on_min_altitude_changed)
        min_altitude_input.setMaximumWidth(100)
        alt_layout.addWidget(QLabel("Min Altitude"))
        alt_layout.addWidget(min_altitude_input)
        config_layout.addLayout(alt_layout)

        hours_layout = QHBoxLayout()
        hours_input = QLineEdit()
        hours_input.setPlaceholderText(str(self.config["hours"]))
        hours_input.textChanged.connect(self.on_hours_changed)
        hours_input.setMaximumWidth(100)
        hours_layout.addWidget(QLabel("Hours"))
        hours_layout.addWidget(hours_input)
        config_layout.addLayout(hours_layout)

        # Lat lon
        lat_lon_layout = QHBoxLayout()

        lat_widget = QLineEdit()
        lon_widget = QLineEdit()
        lat_widget.setPlaceholderText(str(self.config["lat"]))
        lon_widget.setPlaceholderText(str(self.config["lon"]))
        lat_widget.textChanged.connect(self.update_latitude)
        lon_widget.textChanged.connect(self.update_longitude)

        lat_lon_layout.addWidget(QLabel("Latitude:"))
        lat_lon_layout.addWidget(lat_widget)
        lat_lon_layout.addWidget(QLabel("Longitude:"))
        lat_lon_layout.addWidget(lon_widget)
        config_layout.addLayout(lat_lon_layout)

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

        refresh_btn = QPushButton("Refresh Passes")
        refresh_btn.clicked.connect(self.refresh_data)
        config_layout.addWidget(refresh_btn)

        bottom_left_layout.addLayout(config_layout, stretch=1)

        # Add table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Satellite", f"Start Time", f"End Time", "Max Alt"])
        bottom_left_layout.addWidget(self.table, stretch=2)
        self.table.itemSelectionChanged.connect(self.on_table_selection_changed)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        # Right layout for plots
        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout)

        # Add Current Events plot
        self.fig, self.ax = plt.subplots(subplot_kw={'projection': 'polar'})
        self.canvas = FigureCanvas(self.fig)
        right_layout.addWidget(self.canvas)

        # Add Single plot
        self.single_fig, self.single_ax = plt.subplots(subplot_kw={'projection': 'polar'})
        self.single_canvas = FigureCanvas(self.single_fig)
        right_layout.addWidget(self.single_canvas)
        self.single_ax.text(0, 0, "Select a pass to view", horizontalalignment='center', verticalalignment='center', fontsize=24)
        self.single_ax.set_xticks([])
        self.single_ax.set_yticks([])
        self.single_ax.spines['polar'].set_visible(False)

        # Timer for updating plot
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_current_plot)
        self.timer.start(1000)

        self.map_timer = QTimer(self)
        self.map_timer.timeout.connect(self.update_map_plot)
        self.map_timer.start(5000)

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
        print(f"Refreshed {len(self.satellites)} satellites. Found {len(self.events)} passes.")
        
        self.refresh_table()
        self.update_current_plot()
        self.update_sat_list()
        self.update_single_plot(None)
        self.update_map_plot()

        self.writeConfig()

    def on_refresh_data_error(self, error_message):
        self.table.setDisabled(False)  # Re-enable UI even on error
        print(f"Error refreshing data: {error_message}")

    def stop_all_workers(self):
        for worker in self.active_workers:
            worker.stop()

    def refresh_table(self):
        self.table.setRowCount(len(self.events))

        timezone = pytz.timezone(self.config["timezone"])
        now = datetime.now(timezone)
        abr_timezone = now.tzname()

        self.table.setHorizontalHeaderLabels(["Satellite", f"Start Time - {abr_timezone}", f"End Time - {abr_timezone}", "Max Alt"])

        for i, event in enumerate(self.events):
            self.table.setItem(i, 0, QTableWidgetItem(event["satellite"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(event["startTime"].astimezone(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S'))))
            self.table.setItem(i, 2, QTableWidgetItem(str(event["endTime"].astimezone(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S'))))
            self.table.setItem(i, 3, QTableWidgetItem(f"{event['maxAlt']:.0f}"))

        # Resize the time cols to fit the content
        self.table.resizeColumnsToContents()
        # Don't let the table be edited
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.table.setAlternatingRowColors(True)
        
        self.table.setSortingEnabled(True)

        # Default sorting by start time
        self.table.sortItems(1, Qt.AscendingOrder)


    def update_current_plot(self):
        self.ax.clear()
    
        events = [
            event
            for event in self.events
            if event["startTime"] < self.ts.now() < event["endTime"]
        ]
    
        if events:
            # Plot current passes
            plot_events(self.satellites, events, self.ts, self.topo, self.ax)
            self.ax.title.set_text(
                f"Current Passes - {self.ts.now().astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')}"
            )


            #Show the circle and the north south east west labels

            self.ax.set_xticks(np.radians([0, 90, 180, 270]))
            self.ax.set_xticklabels(['N', 'E', 'S', 'W'])
            self.ax.spines['polar'].set_visible(True)


        else:
            # No current passes
            next_pass = next(
                (event for event in self.events if event["startTime"] > self.ts.now()), None
            )
    
            self.ax.title.set_text("")
            self.ax.text(
                0.5,
                0.5,
                "No Current Passes",
                horizontalalignment="center",
                verticalalignment="center",
                transform=self.ax.transAxes,
            )
    
            if next_pass:
                # Calculate time till next pass
                time_till_next_pass = next_pass["startTime"].utc_datetime() -  datetime.now().astimezone(pytz.timezone('UTC'))

                countdown_str = str(time_till_next_pass).split(".")[0]

                next_pass_string = (
                    f"Next Pass {next_pass['satellite']}\n"
                    f"{next_pass['startTime'].astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')}\nT-{countdown_str}"
                )

                self.ax.text(
                    0.5,
                    0.4,
                    next_pass_string,
                    horizontalalignment="center",
                    verticalalignment="center",
                    transform=self.ax.transAxes,
                )

                # Clear all tick marks

                self.ax.set_xticks([])
                self.ax.set_yticks([])
                self.ax.set_yticklabels([])
                self.ax.set_xticklabels([])


                # Clear circle around the polar plot
                self.ax.spines['polar'].set_visible(False)

        self.ax.figure.canvas.draw_idle()

    def update_single_plot(self, event):

        self.single_ax.clear()
        if not event:
            return

        try:
          sat = [sat for sat in self.satellites if sat.name == event["satellite"]][0]
        except IndexError:
            print(f"Satellite {event['satellite']} not found")
            return

        plot_event(sat, event, self.ts, self.topo, ax=self.single_ax)
        self.single_ax.title.set_text(f"{event['satellite']} Pass - {event['startTime'].astimezone(pytz.timezone('US/Eastern')).strftime('%m/%d - %H:%M:%S')}")
        self.single_canvas.draw()

    def on_table_selection_changed(self):
        selected_items = self.table.selectedItems()
        
        if selected_items:
            selected_row = selected_items[0].row()
            name = self.table.item(selected_row, 0).text()
            start_time = self.table.item(selected_row, 1).text()

            print(f"Selected {name} at {start_time}")

            selected_event = None

            for event in self.events:
                if event["satellite"] == name and event["startTime"].astimezone(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d %H:%M:%S') == start_time:
                    self.selected_sat = event["satellite"]
                    self.update_single_plot(event)
                    self.update_map_plot()

            if self.selected_sat is None:
                print(f"Could not find {name} at {start_time}")

        else:
            self.selected_sat = None

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

    def update_latitude(self, text):
        try:
            float_lat = float(text)
            self.config["lat"] = float_lat
        except ValueError:
            pass

    def update_longitude(self, text):
        try:
            float_lon = float(text)
            self.config["lon"] = float_lon
        except ValueError:
            pass

    def update_map_plot(self):

        sats = self.satellites

        if not self.config["filter_enabled"]:
            # Limit to 20 satellites for legibility
            sats = sats[:20]

        plot_map(sats, self.ts, self.config, ax=self.ax_map, my_map=self.map, selected=self.selected_sat)
        self.canvas_map.draw_idle()

    def writeConfig(self):
        with open(self.config["config"], 'w') as f:
            json.dump(self.config, f, indent=4)


def initialize_map(ax):
    ax.clear()
    my_map = Basemap(ax=ax, projection="mill", resolution="l", llcrnrlat=-90, urcrnrlat=90, llcrnrlon=-180, urcrnrlon=180)
    my_map.drawmapboundary(fill_color='aqua')
    my_map.fillcontinents(color='gray',lake_color='aqua')
    return my_map

def plot_map(satellites, ts, config, ax=None, my_map=None, selected=None):

    if ax is None:
        fig = plt.figure(figsize(12, 8))

    if my_map is None:
        my_map = initialize_map(ax)

    else:
        # Clear only the dynamic elements
        for artist in ax.lines + ax.texts:
            artist.remove()


    now = ts.now()

    for sat in satellites:
        geocentric = sat.at(now)
        subpoint = geocentric.subpoint()
        lat = subpoint.latitude.degrees
        lon = subpoint.longitude.degrees
        x, y = my_map(lon, lat)

        color = "blue" 

        if selected is not None and (sat.name == selected):
            color = "yellow"
        my_map.plot(x, y, 'o', markersize=3, color=color)
        ax.text(x, y-.2, sat.name, fontsize=10, ha='center', va='top', color=color)


    # Plot the observer
    my_map.plot(*my_map(config["lon"], config["lat"]), 'rx', markersize=10)

    return my_map

def fetchData(config, url):

    tle_dir = os.path.expanduser(config["tle"])

    # hash the url to get a unique filename
    hsh = hashlib.md5(url.encode()).hexdigest()

    # check if directory exists
    if not os.path.exists(tle_dir):
        os.makedirs(tle_dir)

    # check if file exists
    text_string = None

    refresh = False

    tle_file = f'{tle_dir}/{hsh}.txt'

    if os.path.exists(tle_file):
        # check if file is older than 1 day
        if (time.time() - os.path.getmtime(tle_dir)) > 86400:
            # file is older than 1 day, refresh
            refresh = True
            

        else:
            # file is not older than 1 day, load from file
            with open(tle_file, 'r') as f:
                text_string = f.read()

    else:
        # file does not exist, refresh
        refresh = True

    if refresh:
         response = requests.get(url)
         text_string = response.content
         text_string = text_string.decode('utf-8')

         with open(tle_file, 'w') as f:
             f.write(text_string)

    return text_string

def fetchAllData(config, ts):
  all_sats = []

  for url in config["urls"]:
    # Get the json data from the URL

    text_string = fetchData(config, url)
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

  print(f"Found {len(all_sats)} satellites. Using {len(filtered_sats)}/{len(all_sats)}")

  return filtered_sats, all_sats

DEFAULT_CONFIG  = {
    "urls": [
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=weather&FORMAT=json",
        "https://celestrak.org/NORAD/elements/gp.php?GROUP=amateur&FORMAT=json"
    ],
    "lat": 40.7128,
    "lon": -74.006,
    "timezone": "America/New_York",
    "filter_enabled": 2,
    "satellites": [
        "NOAA 15",
        "NOAA 18",
        "NOAA 19",
        "METEOR-M2 2",
        "METEOR-M2 3",
        "ISS (ZARYA)",
        "SONATE-2",
        "NOAA 20 (JPSS-1)",
        "NOAA 21 (JPSS-2)",
        "FOX-1A (AO-85)",
        "FOX-1CLIFF (AO-95)",
        "FUNCUBE-1 (AO-73)"
    ],
    "min_alt": 30,
    "hours": 36,
    "mode": "gui",
    "config": "~/.config/spaceboi/config.json",
    "tle": "~/.local/share/spaceboi/TLE"
}

def main(mode='gui'):
    
  config  = None
  ts = load.timescale()
  i, refreshed, sat_list = 0, False, []

  parser = argparse.ArgumentParser(description='spaceboi')

  parser.add_argument('--mode', type=str, choices=['gui', 'plot', 'cli'], default='gui', required=False, help='Mode to run the program in')
  parser.add_argument('--lat', type=float, required=False, help='Latitude of the observer')
  parser.add_argument('--lon', type=float, required=False, help='Longitude of the observer')
  parser.add_argument('--min_alt', type=int, required=False, help='Minimum altitude of the satellite')
  parser.add_argument('--hours', type=int, required=False, help='Number of hours to calculate passes')
  parser.add_argument('--satellites', type=str, nargs='+', required=False, help='Satellites to filter')
  parser.add_argument('--filter_enabled', action='store_true', help='Filter satellites')
  parser.add_argument('--timezone', type=str, required=False, help='Timezone of the observer')
  parser.add_argument('--config', type=str, required=False, help='Configuration file', default='~/.config/spaceboi/config.json')
  parser.add_argument('--tle', type=str, required=False, default="~/.local/share/spaceboi/TLE", help='TLE Cache directory')

  args = parser.parse_args()
  
  args.config = os.path.expanduser(args.config)

  if not os.path.exists(args.config):
    print(f"Configuration file {args.config} not found")
    print(f"Creating default configuration at {args.config}")

    os.makedirs(os.path.dirname(args.config), exist_ok=True)
    with open(args.config, 'w') as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)

  with open(args.config, 'r') as f:
    print(f"Loading configuration from {args.config}")
    config = json.load(f)

  for key, value in vars(args).items():
    if value:
      config[key] = value

  config["tle"] = os.path.expanduser(args.tle)

  if args.mode == 'plot':
    topo = Topos(config["lat"], config["lon"])
    satellites, all_sats = fetchAllData(config, ts)
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
    satellites, all_sats = fetchAllData(config, ts)
    events = []
    for sat in satellites:
      events.extend(calcPasses(sat, t, config["hours"], topo, config["min_alt"]))

    # Sort by time

    events.sort(key=lambda x: x['startTime'])

    for event in events:
        print(formatPass(event, pytz.timezone('US/Eastern')))

if __name__ == "__main__":
    main()
