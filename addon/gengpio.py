#!/usr/bin/env python
#-------------------------------------------------------------------------------
#    FILE: gengpio.py
# PURPOSE: genmon.py support program to allow GPIO pints to drive
# status LEDs
#
#  AUTHOR: Jason G Yates
#    DATE: 05-Apr-2016
#
# MODIFICATIONS:
#-------------------------------------------------------------------------------

import datetime, time, sys, signal, os, json
try:
    # this will add the parent of the genmonlib folder to the path
    # if we are one level below the genmonlib parent (e.g. in the addon folder)
    file_root = os.path.dirname(os.path.realpath(__file__))
    parent_root=os.path.abspath(os.path.join(file_root, os.pardir))
    if os.path.isdir(os.path.join(parent_root, "genmonlib")):
        sys.path.insert(1, parent_root)

    from genmonlib.myconfig import MyConfig
    from genmonlib.mylog import SetupLogger
    from genmonlib.myclient import ClientInterface
    from genmonlib.mysupport import MySupport
except Exception as e1:
    print("\n\nThis program requires the modules located in the genmonlib directory in the github repository.\n")
    print("Please see the project documentation at https://github.com/jgyates/genmon.\n")
    print("Error: " + str(e1))
    sys.exit(2)

import RPi.GPIO as GPIO

#----------  InitGPIO ----------------------------------------------------------
def InitGPIO(pin, direction = GPIO.OUT, initial = GPIO.LOW):

    try:
        if pin != 0:
            GPIO.setup(pin, direction, initial = initial)
        else:
            log.error("Error: pin = 0 in InitGPIO")
    except Exception as e1:
        log.error("Error in InitGPIO on pin %d : %s" %(int(pin), str(e1)))

#----------  SetGPIO -----------------------------------------------------------
def SetGPIO(pin, state):

    try:
        if pin != 0:
            GPIO.output(pin,state)
        else:
            log.error("Error: pin = 0 in SetGPIO")
    except Exception as e1:
        log.error("Error in InitGPIO on SetGPIO %d : %s" %(int(pin), str(e1)))

#----------  Signal Handler ----------------------------------------------------
def signal_handler(signal, frame):

    GPIO.cleanup()
    MyClientInterface.Close()
    sys.exit(0)

#------------------- Command-line interface for gengpio ------------------------
if __name__=='__main__': # usage program.py [server_address]

    try:
        console, ConfigFilePath, address, port, loglocation, log = MySupport.SetupAddOnProgram("gengpio")

        # Set the signal handler
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        MyClientInterface = ClientInterface(host = address, port = port, log = log)

        config = MyConfig(filename =  os.path.join(ConfigFilePath, 'gengpio.conf'), section = 'gengpio', log = log)
        #setup GPIO using Board numbering
        GPIO.setmode(GPIO.BOARD)

        console.info( GPIO.RPI_INFO)

        GPIO.setwarnings(False)

        TimeUpdated = datetime.datetime(2000, 1, 1, 1, 00)

        # These are the GPIP pins numbers on the Raspberry PI GPIO header
        # https://www.element14.com/community/servlet/JiveServlet/previewBody/73950-102-10-339300/pi3_gpio.png
        # Commnet out or Uncomment the GPIO and Generator status and alarms you wish to monitor.  Limited on GPIO.
        STATUS_READY = config.ReadValue('STATUS_READY', return_type = int, default = 16)
        STATUS_ALARM = config.ReadValue('STATUS_ALARM', return_type = int, default = 18)
        STATUS_SERVICE = config.ReadValue('STATUS_SERVICE', return_type = int, default = 22)
        STATUS_RUNNING = config.ReadValue('STATUS_RUNNING', return_type = int, default = 26)
        STATUS_EXERCISING = config.ReadValue('STATUS_EXERCISING', return_type = int, default = 24)
        STATUS_OFF = config.ReadValue('STATUS_OFF', return_type = int, default = 21)

        # Set additional GPIO based on these error codes
        ER_GENMON = config.ReadValue('ER_GENMON', return_type = int, default = 3)
        ER_INTERNET = config.ReadValue('ER_INTERNET', return_type = int, default = 5)
        ER_SPEED = config.ReadValue('ER_SPEED', return_type = int, default = 29)
        ER_LOW_OIL = config.ReadValue('ER_LOW_OIL', return_type = int, default = 31)
        ER_HIGH_TEMP = config.ReadValue('ER_HIGH_TEMP', return_type = int, default = 33)
        ER_RPM_SENSE = config.ReadValue('ER_RPM_SENSE', return_type = int, default = 35)
        ER_VOLTAGE = config.ReadValue('ER_VOLTAGE', return_type = int, default = 37)
        ER_OVERCRANK = config.ReadValue('ER_OVERCRANK', return_type = int, default = 40)
        ER_OVERLOAD = config.ReadValue('ER_OVERLOAD', return_type = int, default = 38)
        ER_GOVERNOR = config.ReadValue('ER_GOVERNOR', return_type = int, default = 36)
        ER_WARNING = config.ReadValue('ER_WARNING', return_type = int, default = 32)

        # Other Faults
        #ER_Controller = config.ReadValue('ER_Controller', return_type = int, default = 3) # Must chose from available GPIO
        #ER_Ignition = config.ReadValue('ER_Ignition', return_type = int, default = ) # Must chose from available GPIO
        #ER_Low_Fuel = config.ReadValue('ER_Low_Fuel', return_type = int, default = ) # Must chose from available GPIO
        #ER_Low_Coolant = config.ReadValue('ER_Low_Coolant', return_type = int, default = ) # Must chose from available GPIO
        #ER_Battery_Problem = config.ReadValue('ER_Battery_Problem', return_type = int, default = ) # Must chose from available GPIO
        #ER_Charger = config.ReadValue('ER_Charger', return_type = int, default = ) # Must chose from available GPIO

        InitGPIO(STATUS_READY, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(STATUS_ALARM, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(STATUS_SERVICE, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(STATUS_RUNNING, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(STATUS_EXERCISING, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(STATUS_OFF, GPIO.OUT, initial=GPIO.LOW)

        InitGPIO(ER_GENMON, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_INTERNET, GPIO.OUT, initial=GPIO.LOW)

        InitGPIO(ER_SPEED, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_LOW_OIL, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_HIGH_TEMP, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_RPM_SENSE, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_VOLTAGE, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_OVERCRANK, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_OVERLOAD, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_GOVERNOR, GPIO.OUT, initial=GPIO.LOW)
        InitGPIO(ER_WARNING, GPIO.OUT, initial=GPIO.LOW)

        # Other Faults
        #InitGPIO(ER_Controller, GPIO.OUT, initial=GPIO.LOW)
        #InitGPIO(ER_Ignition, GPIO.OUT, initial=GPIO.LOW)
        #InitGPIO(ER_Low_Fuel, GPIO.OUT, initial=GPIO.LOW)
        #InitGPIO(ER_Low_Coolant, GPIO.OUT, initial=GPIO.LOW)
        #InitGPIO(ER_Battery_Problem, GPIO.OUT, initial=GPIO.LOW)
        #InitGPIO(ER_Charger, GPIO.OUT, initial=GPIO.LOW)

        LastEvent = ""
        LastNetStatus = ""
        LastMonitorHealth = ""

        data = MyClientInterface.ProcessMonitorCommand("generator: monitor")

        if "evolution" in data.lower():
            Evolution = True
            console.info ("Evolution Controller Detected\n")
        else:
            Evolution = False
            console.info ("Non Evolution Controller Detected\n")

        while True:


            data = MyClientInterface.ProcessMonitorCommand("generator: getbase")

            if LastEvent != data:
                LastEvent = data
                console.info ("State: " + data)

                if data == "READY":
                    SetGPIO(STATUS_READY,GPIO.HIGH)
                else:
                    SetGPIO(STATUS_READY,GPIO.LOW)

                if data == "EXERCISING":
                    SetGPIO(STATUS_EXERCISING,GPIO.HIGH)
                else:
                    SetGPIO(STATUS_EXERCISING,GPIO.LOW)

                if data == "RUNNING" or data == "RUNNING-MANUAL":
                    SetGPIO(STATUS_RUNNING,GPIO.HIGH)
                else:
                    SetGPIO(STATUS_RUNNING,GPIO.LOW)

                if data == "ALARM":
                    SetGPIO(STATUS_ALARM,GPIO.HIGH)
                else:
                    SetGPIO(STATUS_ALARM,GPIO.LOW)

                if data == "SERVICEDUE":
                    SetGPIO(STATUS_SERVICE,GPIO.HIGH)
                else:
                    SetGPIO(STATUS_SERVICE, GPIO.LOW)

                if data == "OFF" or data == "MANUAL":
                    SetGPIO(STATUS_OFF,GPIO.HIGH)
                else:
                    SetGPIO(STATUS_OFF, GPIO.LOW)


                if data == "ALARM" and Evolution:     # Last Error Code not supported by Nexus

                    # get last error code
                    data = MyClientInterface.ProcessMonitorCommand("generator: getregvalue=05f1")
                    LastErrorCode = int(data,16)

                    # Overspeed/Underspeed (alarms 1200s, 1600s)
                    if 1200 <= LastErrorCode <= 1299 or 1600 <= LastErrorCode <= 1699:
                        SetGPIO(ER_SPEED,GPIO.HIGH)

                    # Low Oil (alarm 1300s)
                    if 1300 <= LastErrorCode <= 1399:
                        SetGPIO(ER_LOW_OIL,GPIO.HIGH)

                    # High Temp (alarm 1400s)
                    if 1400 <= LastErrorCode <= 1499:
                        SetGPIO(ER_HIGH_TEMP,GPIO.HIGH)

                    # RPM Sensor (alarm 1500s)
                    if 1500 <= LastErrorCode <= 1599:
                        SetGPIO(ER_RPM_SENSE,GPIO.HIGH)

                    # Overvoltage/Undervoltage (alarm 1800s, 1900s)
                    if 1800 <= LastErrorCode <= 1899 or 1900 <= LastErrorCode <= 1999:
                        SetGPIO(ER_VOLTAGE,GPIO.HIGH)

                    # Overcrank (alarm 1100s)
                    if 1100 <= LastErrorCode <= 1199:
                        SetGPIO(ER_OVERCRANK,GPIO.HIGH)

                    # Overload (alarm 2100s)
                    if 2100 <= LastErrorCode <= 2199:
                        SetGPIO(ER_OVERLOAD,GPIO.HIGH)

                    # Governor (alarm 2500s)
                    if 2500 <= LastErrorCode <= 2599:
                        SetGPIO(ER_GOVERNOR,GPIO.HIGH)

                    # Warning (alarm 0000)
                    if 0000 == LastErrorCode:
                        SetGPIO(ER_WARNING,GPIO.HIGH)

                    # Controller Internal (alarm 1000s)
                    #if 1000 <= LastErrorCode <= 1099:
                    #    SetGPIO(ER_Controller,GPIO.HIGH)

                    # Ignition (alarm 2600-2669)
                    #if 2600 <= LastErrorCode <= 2669:
                    #    SetGPIO(ER_Ignition,GPIO.HIGH)

                    # Fuel Level (alarm 2680 and 2700)
                    #if LastErrorCode == 2680 or LastErrorCode == 2700:
                    #    SetGPIO(ER_Low_Fuel,GPIO.HIGH)

                    # Low Coolant (alarm 2720)
                    #if LastErrorCode == 2720:
                    #    SetGPIO(ER_Low_Coolant,GPIO.HIGH)

                    # Battery (alarm 2750 and 2760)
                    #if LastErrorCode == 2750 or LastErrorCode == 2760:
                    #    SetGPIO(ER_Battery_Problem,GPIO.HIGH)

                    # Charger (alarm 2770 and 2780)
                    #if LastErrorCode == 2770 or LastErrorCode == 2780:
                    #    SetGPIO(ER_Charger,GPIO.HIGH)

                else:
                    SetGPIO(ER_SPEED,GPIO.LOW)
                    SetGPIO(ER_LOW_OIL,GPIO.LOW)
                    SetGPIO(ER_HIGH_TEMP,GPIO.LOW)
                    SetGPIO(ER_RPM_SENSE,GPIO.LOW)
                    SetGPIO(ER_VOLTAGE,GPIO.LOW)
                    SetGPIO(ER_OVERCRANK,GPIO.LOW)
                    SetGPIO(ER_OVERLOAD,GPIO.LOW)
                    SetGPIO(ER_GOVERNOR,GPIO.LOW)
                    SetGPIO(ER_WARNING,GPIO.LOW)
                    #SetGPIO(ER_Controller,GPIO.LOW)
                    #SetGPIO(ER_Ignition,GPIO.LOW)
                    #SetGPIO(ER_Low_Fuel,GPIO.LOW)
                    #SetGPIO(ER_Low_Coolant,GPIO.LOW)
                    #SetGPIO(ER_Battery_Problem,GPIO.LOW)
                    #SetGPIO(ER_Charger,GPIO.LOW)

            # Get Genmon status
            try:
                data = MyClientInterface.ProcessMonitorCommand("generator: monitor_json")
                TempDict = {}
                TempDict = json.loads(data)
                HealthStr = TempDict["Monitor"][0]["Generator Monitor Stats"][0]["Monitor Health"]
                if HealthStr != LastMonitorHealth:
                    LastMonitorHealth = HealthStr
                    if HealthStr.lower() == "ok":
                        SetGPIO(ER_GENMON,GPIO.LOW)
                    else:
                        SetGPIO(ER_GENMON,GPIO.HIGH)
            except Exception as e1:
                log.error("Error getting monitor health: " +str(e1))
            # get Internet Status
            try:
                # only check this every 20 seconds
                TimeNow = datetime.datetime.now()
                if ((TimeNow - TimeUpdated).total_seconds() > 20):
                    TimeUpdated = TimeNow
                    console.info("Updating internet status: " + str((TimeUpdated)))
                    data = MyClientInterface.ProcessMonitorCommand("generator: network_status")
                    if data != LastNetStatus:
                        LastNetStatus = data
                        if data.lower() == "ok":
                            SetGPIO(ER_INTERNET,GPIO.LOW)
                        else:
                            SetGPIO(ER_INTERNET,GPIO.HIGH)

            except Exception as e1:
                log.error("Error getting internet status: " +str(e1))

            time.sleep(3)

    except Exception as e1:
        log.error("Error: " + str(e1))
        console.error ("Error: " + str(e1))
