#!/usr/bin/env python
#-------------------------------------------------------------------------------
#    FILE: custom_controller.py
# PURPOSE: Controller module for defining a custom generator controller
#
#  AUTHOR: Jason G Yates
#    DATE: 24-Jul-2021
#
# MODIFICATIONS:
#-------------------------------------------------------------------------------

import datetime, time, sys, os, threading, re
import json, collections

from genmonlib.controller import GeneratorController
from genmonlib.mytile import MyTile
from genmonlib.modbus_file import ModbusFile
from genmonlib.mymodbus import ModbusProtocol


class CustomController(GeneratorController):

    #---------------------CustomController::__init__----------------------------
    def __init__(self,
        log,
        newinstall = False,
        simulation = False,
        simulationfile = None,
        message = None,
        feedback = None,
        config = None):

        # call parent constructor
        super(CustomController, self).__init__(log, newinstall = newinstall, simulation = simulation, simulationfile = simulationfile, message = message, feedback = feedback, config = config)

        self.LastEngineState = ""
        self.CurrentAlarmState = False
        self.VoltageConfig = None
        self.AlarmAccessLock = threading.RLock()     # lock to synchronize access to the logs
        self.EventAccessLock = threading.RLock()     # lock to synchronize access to the logs
        self.ConfigValidated = False
        self.ControllerDetected = False
        self.DisableOutageCheck = False
        # for custom controllers
        self.SerialBaudRate = 9600 
        self.SerialParity = None 
        self.SerialOnePointFiveStopBits = False

        self.DaysOfWeek = { 0: "Sunday",    # decode for register values with day of week
                            1: "Monday",
                            2: "Tuesday",
                            3: "Wednesday",
                            4: "Thursday",
                            5: "Friday",
                            6: "Saturday"}
        self.MonthsOfYear = { 1: "January",     # decode for register values with month
                              2: "February",
                              3: "March",
                              4: "April",
                              5: "May",
                              6: "June",
                              7: "July",
                              8: "August",
                              9: "September",
                              10: "October",
                              11: "November",
                              12: "December"}

        self.SetupClass()


    #-------------CustomController:SetupClass-----------------------------------
    def SetupClass(self):

        # read config file
        try:
            if not self.GetConfig():
                self.FatalError("Failure in Controller GetConfig")
                return None
        except Exception as e1:
            self.FatalError("Error reading config file: " + str(e1))
            return None

        try:
            #Starting device connection
            if self.Simulation:
                self.ModBus = ModbusFile(self.UpdateRegisterList,
                    inputfile = self.SimulationFile,
                    config = self.config)
            else:
                self.ModBus = ModbusProtocol(self.UpdateRegisterList, rate = self.SerialBaudRate, 
                    Parity = self.SerialParity, OnePointFiveStopBits = self.SerialOnePointFiveStopBits,
                    config = self.config)


            self.ModBus.AlternateFileProtocol = self.AlternateFileProtocol
            self.Threads = self.MergeDicts(self.Threads, self.ModBus.Threads)
            self.LastRxPacketCount = self.ModBus.RxPacketCount

            self.StartCommonThreads()

        except Exception as e1:
            self.FatalError("Error opening modbus device: " + str(e1))
            return None

    #---------------------CustomController::GetConfig---------------------------
    # read conf file, used internally, not called by genmon
    # return True on success, else False
    def GetConfig(self):

        try:

            self.AlternateFileProtocol = self.config.ReadValue('alternatefileprotocol', return_type = bool, default = True)
            self.VoltageConfig = self.config.ReadValue('voltageconfiguration', default = "277/480")
            self.NominalBatteryVolts = int(self.config.ReadValue('nominalbattery', return_type = int, default = 24))
            self.FuelUnits = self.config.ReadValue('fuel_units', default = "gal")
            self.FuelHalfRate = self.config.ReadValue('half_rate', return_type = float, default = 0.0)
            self.FuelFullRate = self.config.ReadValue('full_rate', return_type = float, default = 0.0)
            self.UseFuelSensor = self.config.ReadValue('usesensorforfuelgauge', return_type = bool, default = True)
            self.UseCalculatedPower = self.config.ReadValue('usecalculatedpower', return_type = bool, default = False)
            self.DisableOutageCheck = self.config.ReadValue('disableoutagecheck', return_type = bool, default = False)
            # used for controllers that use serial comms other than 9600, N, 8, 1
            # NOTE: This is only for custom controllers
            if self.config.HasOption('serial_baud_rate'):
                self.SerialBaudRate = self.config.ReadValue('serial_baud_rate', return_type = int, default = 9600)
            if self.config.HasOption('serial_parity'):
                self.SerialParity = self.config.ReadValue('serial_parity', return_type = int, default = 0)
                if self.SerialParity == 0 or self.SerialParity > 2:
                    self.SerialParity = None
            if self.config.HasOption('serial_one_point_five_stop_bits'):
                self.SerialOnePointFiveStopBits = self.config.ReadValue('serial_one_point_five_stop_bits', return_type = bool, default = False)

            self.ConfigImportFile = self.config.ReadValue('import_config_file', default = None)
            if self.ConfigImportFile == None:
                self.FatalError("Missing entry import_config_file. Unable to continue.")

            self.ConfigFileName = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "data",  "controller", self.ConfigImportFile)

            self.LogError("Using config import: " + self.ConfigFileName)
            if not self.ReadImportConfig():
                self.FatalError("Unable to read import config: " + self.ConfigFileName)
                return False

        except Exception as e1:
            self.FatalError("Missing config file or config file entries (CustomController): " + str(e1))
            return False

        return True

    #-------------CustomController:ReadImportConfig-----------------------------
    def ReadImportConfig(self):

        if os.path.isfile(self.ConfigFileName):
            try:
                with open(self.ConfigFileName) as infile:
                    self.controllerimport = json.load(infile)
            except Exception as e1:
                self.LogErrorLine("Error in GetConfig reading config import file: " + str(e1))
                return False
        else:
            self.LogError("Error reading config import file: " + str(self.ConfigFileName))
            return False

        return True
    #-------------CustomController:GetSingleEntry-------------------------------
    # get a single value from JSON config or a dynamic value from modbus
    # Return either a modbus value or a single numeric value from JSON
    def GetSingleEntry(self, entry_name):
        try:
            if not entry_name in self.controllerimport:
                return False, None
            ImportedEntry = self.controllerimport[entry_name]
            if isinstance(ImportedEntry, dict): 
                ImportedTitle, ImportedValue = self.GetDisplayEntry(ImportedEntry, JSONNum = False, no_units = True)
            else:
                ImportedValue = int(ImportedEntry)
            return True, ImportedValue
        except Exception as e1:
            self.LogErrorLine("Error in GetSingleEntry: " + entry_name + ": " + str(e1))
            return False, None  

    #-------------CustomController:IdentifyController---------------------------
    def IdentifyController(self):

        try:
            self.Model = str(self.controllerimport["controller_name"])

            ReturnValue = False 

            ReturnValue, self.NominalLineVolts = self.GetSingleEntry("rated_nominal_voltage")
            if not ReturnValue:
                return False
            
            ReturnValue, self.NominalBatteryVolts = self.GetSingleEntry("nominal_battery_voltage")
            if not ReturnValue:
                return False
            
            ReturnValue, self.NominalFreq = self.GetSingleEntry("rated_nominal_freq")
            if not ReturnValue:
                return False
            
            ReturnValue, self.NominalRPM = self.GetSingleEntry("rated_nominal_rpm")
            if not ReturnValue:
                return False

            ReturnValue, self.NominalKW = self.GetSingleEntry("rated_max_output_power_kw")
            if not ReturnValue:
                return False

            ReturnValue, self.Phase = self.GetSingleEntry("generator_phase")
            if not ReturnValue:
                return False
            
            self.ControllerDetected = True

        except Exception as e1:
            self.LogErrorLine("Error in IdentifyController: " + str(e1))
            return False

    #-------------CustomController:ValidateConfig---------------------------
    def ValidateConfig(self):

        try:
            if self.ControllerDetected:
                return True

            #at this point we will parse the imported config from the JSON file
            if not "switch_state" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain switch_state")
                return False
            if not "alarm_conditions" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain alarm_conditions")
                return False
            if not "engine_state" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain engine_state")
                return False
            if not "base_registers" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain base_registers")
                return False
            if not "status" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain status")
                return False
            if not "maintenance" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain maintenance")
                return False
            if not "controller_name" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain controller_name")
                return False

            if not "rated_max_output_power_kw" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain rated_max_output_power_kw")
                return False
            if not "rated_nominal_voltage" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain rated_nominal_voltage")
                return False
            if not "rated_nominal_freq" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain rated_nominal_freq")
                return False
            if not "rated_nominal_rpm" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain rated_nominal_rpm")
                return False
            if not "generator_phase" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain generator_phase")
                return False
            if not "nominal_battery_voltage" in self.controllerimport:
                self.LogError("Error: Controller Import does not contain nominal_battery_voltage")
                return False

            for Register, Length in self.controllerimport["base_registers"].items():
                if Length % 2 != 0:
                    self.LogError("Error: Controller Import: modbus register lenghts must be divisible by 2: " + str(Register) + ":" + str(Length))
                    return False

            self.ConfigValidated = True

            return True
        except Exception as e1:
            self.LogErrorLine("Error in ValidateConfig: " + str(e1))
            return False
    #-------------CustomController:InitDevice-----------------------------------
    # One time reads, and read all registers once
    def InitDevice(self):

        try:
            self.ValidateConfig()
            self.MasterEmulation()
            self.IdentifyController()
            self.SetupTiles()
            self.InitComplete = True
            self.InitCompleteEvent.set()
        except Exception as e1:
            self.LogErrorLine("Error in InitDevice: " + str(e1))

    #-------------CustomController:SetupTiles-----------------------------------
    def SetupTiles(self):
        try:
            with self.ExternalDataLock:
                self.TileList = []

            sensor_list = self.controllerimport["gauges"]

            for sensor in sensor_list:

                if "title" not in sensor:
                    self.LogError("Error in SetupTiles: no ""title"" in sensor entry")
                    continue

                if "sensor" not in sensor:
                    self.LogError("Error in SetupTiles: sensor (" + sensor["title"] + ") has no ""sensor"" entry")
                    continue 
                if "units" not in sensor:
                    self.LogError("Error in SetupTiles: sensor (" + sensor["title"] + ") has no ""units"" entry")
                    continue 
                if "nominal" not in sensor:
                    self.LogError("Error in SetupTiles: sensor (" + sensor["title"] + ") has no ""nominal"" entry")
                    continue 
            
                if "maximum" in sensor:
                    maximum = sensor["maximum"]
                else:
                    maximum = None
                if "values" in sensor:
                    values = sensor["values"]
                else:
                    values = None
                Tile = MyTile(self.log, title = sensor["title"],
                    type = sensor["sensor"], units = sensor["units"], nominal = sensor["nominal"],
                    maximum = maximum, values = values, callback = self.GetGaugeValue,
                    callbackparameters = (sensor["title"],))
                self.TileList.append(Tile)

            self.SetupCommonTiles()

        except Exception as e1:
            self.LogErrorLine("Error in SetupTiles: " + str(e1))

    #------------ CustomController:WaitAndPergeforTimeout ----------------------
    def WaitAndPergeforTimeout(self):
        # if we get here a timeout occured, and we have recieved at least one good packet
        # this logic is to keep from receiving a packet that we have already requested once we
        # timeout and start to request another
        # Wait for a bit to allow any missed response from the controller to arrive
        # otherwise this could get us out of sync
        # This assumes MasterEmulation is called from ProcessThread
        if self.WaitForExit("ProcessThread", float(self.ModBus.ModBusPacketTimoutMS / 1000.0)):  #
            return
        self.ModBus.Flush()

    #-------------CustomController:MasterEmulation------------------------------
    def MasterEmulation(self):

        try:
            if not self.ConfigValidated:
                self.ValidateConfig()
                if not self.ConfigValidated:
                    return
            if not self.ControllerDetected:
                self.IdentifyController()
                if not self.ControllerDetected:
                    return
            for Register, Length in self.controllerimport["base_registers"].items():
                try:
                    if self.IsStopping:
                        return
                    localTimeoutCount = self.ModBus.ComTimoutError
                    localSyncError = self.ModBus.ComSyncError
                    self.ModBus.ProcessTransaction(Register, Length / 2)
                    if ((localSyncError != self.ModBus.ComSyncError or localTimeoutCount != self.ModBus.ComTimoutError)
                        and self.ModBus.RxPacketCount):
                        self.WaitAndPergeforTimeout()
                except Exception as e1:
                    self.LogErrorLine("Error in MasterEmulation: " + str(e1))

            self.CheckForAlarmEvent.set()
        except Exception as e1:
            self.LogErrorLine("Error in MasterEmulation: " + str(e1))

    #------------ CustomController:GetTransferStatus ---------------------------
    def GetTransferStatus(self):

        LineState = "Unknown"
        # TODO

        return LineState

    #------------ Evolution:CheckForOutage -------------------------------------
    # also update min and max utility voltage
    def CheckForOutage(self):

        try:
            if not self.InitComplete:
                return

            if not self.OutageSupported():
                return 

            # get utility voltage, threshold voltage and pickup voltage 
            ReturnValue, UtilityVolts = self.GetSingleEntry("linevoltage")
            if not ReturnValue or UtilityVolts == None:
                return
            ReturnValue, ThresholdVoltage = self.GetSingleEntry("thresholdvoltage")
            if not ReturnValue or ThresholdVoltage == 0 or ThresholdVoltage == None:
                ThresholdVoltage = int(self.NominalLineVolts * .60)

            ReturnValue, PickupVoltage = self.GetSingleEntry("pickupvoltage")
            if not ReturnValue or PickupVoltage == 0 or PickupVoltage == None:
                PickupVoltage = int(self.NominalLineVolts * .80)

            ThresholdVoltage = int(ThresholdVoltage)
            PickupVoltage = int(PickupVoltage)

            self.CheckForOutageCommon( UtilityVolts, ThresholdVoltage, PickupVoltage)

        except Exception as e1:
            self.LogErrorLine("Error in CheckForOutage: " + str(e1))

    #------------ CustomController:CheckForAlarms ------------------------------
    def CheckForAlarms(self):

        try:
            status_included = False
            if not self.InitComplete:
                return

            if self.OutageSupported():
                self.CheckForOutage()

            # Check for changes in engine state
            EngineState = self.GetEngineState()
            EngineState += self.GetSwitchState()
            msgbody = ""

            if len(self.UserURL):
                msgbody += "For additional information : " + self.UserURL + "\n"
            if not EngineState == self.LastEngineState:
                self.LastEngineState = EngineState
                msgsubject = "Generator Notice: " + self.SiteName
                if not self.SystemInAlarm():
                    msgbody += "NOTE: This message is a notice that the state of the generator has changed. The system is not in alarm.\n"
                    MessageType = "info"
                else:
                    MessageType = "warn"
                msgbody += self.DisplayStatus()
                status_included = True
                self.MessagePipe.SendMessage(msgsubject , msgbody, msgtype = MessageType)

            # Check for Alarms
            if self.SystemInAlarm():
                if not self.CurrentAlarmState:
                    msgsubject = "Generator Notice: ALARM Active at " + self.SiteName
                    if not status_included:
                        msgbody += self.DisplayStatus()
                    self.MessagePipe.SendMessage(msgsubject , msgbody, msgtype = "warn")
            else:
                if self.CurrentAlarmState:
                    msgsubject = "Generator Notice: ALARM Clear at " + self.SiteName
                    if not status_included:
                        msgbody += self.DisplayStatus()
                    self.MessagePipe.SendMessage(msgsubject , msgbody, msgtype = "warn")

            self.CurrentAlarmState = self.SystemInAlarm()

        except Exception as e1:
            self.LogErrorLine("Error in CheckForAlarms: " + str(e1))

        return


    #------------ CustomController:UpdateRegisterList --------------------------
    def UpdateRegisterList(self, Register, Value, IsString = False, IsFile = False):

        try:
            if len(Register) != 4:
                self.LogError("Validation Error: Invalid register value in UpdateRegisterList: %s %s" % (Register, Value))
                return False

            if not IsFile:
                #  validate data length
                length = len(Value) / 2
                reg_dict = self.controllerimport["base_registers"]
                if reg_dict[Register] != length:
                    self.LogError("Invalid length detected in received modbus regisger " + str(Register) + " : " + str(length ) + ": " + str(self.controllerimport["base_registers"]))
                    return False
                else:
                    self.Registers[Register] = Value
            else:
                # todo validate file data length
                self.FileData[Register] = Value
            return True
        except Exception as e1:
            self.LogErrorLine("Error in UpdateRegisterList: " + str(e1))
            return False

    #---------------------CustomController::SystemInAlarm-----------------------
    # return True if generator is in alarm, else False
    def SystemInAlarm(self):

        try:
            if not "alarm_active" in self.controllerimport:
                alarms = self.GetExtendedDisplayString(self.controllerimport, "alarm_conditions")
                if alarms == "Unknown":
                    return False
                return True
            alarm_state = self.GetExtendedDisplayString(self.controllerimport, "alarm_active")
            if len(alarm_state) and not alarm_state == "Unknown" :
                return True
            return False
        except Exception as e1:
            self.LogErrorLine("Error in SystemInAlarm: " + str(e1))
            return False
    #------------ CustomController:GetSwitchState ------------------------------
    def GetSwitchState(self):

        try:
            return self.GetExtendedDisplayString(self.controllerimport, "switch_state")
        except Exception as e1:
            self.LogErrorLine("Error in GetSwitchState: " + str(e1))
            return "Unknown"

    #------------ CustomController:GetGeneratorStatus --------------------------
    def GetGeneratorStatus(self):

        try:
            generator_status = self.GetExtendedDisplayString(self.controllerimport, "generator_status")
            return generator_status
        except Exception as e1:
            self.LogErrorLine("Error in GetGeneratorStatus: " + str(e1))
            return "Unknown"

    #------------ CustomController:GetEngineState ------------------------------
    def GetEngineState(self):

        try:
            return self.GetExtendedDisplayString(self.controllerimport, "engine_state")

        except Exception as e1:
            self.LogErrorLine("Error in GetEngineState: " + str(e1))
            return "Unknown"

    #------------ CustomController:GetDateTime ----------------------------------------
    def GetDateTime(self):

        ErrorReturn = "Unknown"
        try:
            # TODO
            return ErrorReturn
        except Exception as e1:
            self.LogErrorLine("Error in GetDateTime: " + str(e1))
            return ErrorReturn

    #------------ CustomController::OutageSupported -----------------------------------
    def OutageSupported(self):

        if self.DisableOutageCheck:
            # do not check for outage
            return False 

        if "linevoltage" in self.controllerimport.keys():
            if "thresholdvoltage" in self.controllerimport.keys():
                if "pickupvoltage" in self.controllerimport.keys():
                    return True

        return False 

    #------------ CustomController::GetStartInfo --------------------------------------
    # return a dictionary with startup info for the gui
    def GetStartInfo(self, NoTile = False):

        try:
            StartInfo = {}

            StartInfo["fueltype"] = self.FuelType
            StartInfo["model"] = self.Model
            StartInfo["nominalKW"] = self.NominalKW
            StartInfo["nominalRPM"] = self.NominalRPM
            StartInfo["nominalfrequency"] = self.NominalFreq
            StartInfo["phase"] = self.Phase
            StartInfo["PowerGraph"] = self.PowerMeterIsSupported()
            StartInfo["NominalBatteryVolts"] = self.NominalBatteryVolts
            StartInfo["FuelCalculation"] = self.FuelTankCalculationSupported()
            StartInfo["FuelSensor"] = self.FuelSensorSupported()
            StartInfo["FuelConsumption"] = self.FuelConsumptionSupported()
            StartInfo["Controller"] = self.GetController()
            StartInfo["UtilityVoltage"] = False
            StartInfo["RemoteCommands"] = False      # Remote Start/ Stop/ StartTransfer
            StartInfo["ResetAlarms"] = False
            StartInfo["AckAlarms"] = False
            StartInfo["RemoteTransfer"] = False    # Remote start and transfer command
            StartInfo["RemoteButtons"] = False      # Remote controll of Off/Auto/Manual
            StartInfo["ExerciseControls"] = False  # self.SmartSwitch
            StartInfo["WriteQuietMode"] = False
            StartInfo["SetGenTime"] = False
            if self.Platform != None:
                StartInfo["Linux"] = self.Platform.IsOSLinux()
                StartInfo["RaspbeerryPi"] = self.Platform.IsPlatformRaspberryPi()
            
            if not NoTile:

                StartInfo["buttons"] = self.GetButtons()

                StartInfo["pages"] = {
                                "status":True,
                                "maint":True,
                                "outage":self.OutageSupported(),
                                "logs":False,
                                "monitor": True,
                                "maintlog" : True,
                                "notifications": True,
                                "settings": True,
                                "addons": True,
                                "about": True
                                }

                StartInfo["tiles"] = []
                for Tile in self.TileList:
                    StartInfo["tiles"].append(Tile.GetStartInfo())

        except Exception as e1:
            self.LogErrorLine("Error in GetStartInfo: " + str(e1))

        return StartInfo
    
    #------------ CustomController::GetStatusForGUI -----------------------------------
    # return dict for GUI
    def GetStatusForGUI(self):

        try:
            Status = {}

            Status["basestatus"] = self.GetBaseStatus()
            Status["switchstate"] = self.GetSwitchState()
            Status["enginestate"] = self.GetEngineState()
            Status["kwOutput"] = self.GetPowerOutput()
            # Exercise Info is a dict containing the following:
            # Not supported
            ExerciseInfo = collections.OrderedDict()
            ExerciseInfo["Enabled"] = False
            ExerciseInfo["Frequency"] = "Weekly"    # Biweekly, Weekly or Monthly
            ExerciseInfo["Hour"] = "14"
            ExerciseInfo["Minute"] = "00"
            ExerciseInfo["QuietMode"] = "Off"
            ExerciseInfo["EnhancedExerciseMode"] = False
            ExerciseInfo["Day"] = "Monday"
            Status["ExerciseInfo"] = ExerciseInfo

            Status["tiles"] = []
            for Tile in self.TileList:
                Status["tiles"].append(Tile.GetGUIInfo())

        except Exception as e1:
            self.LogErrorLine("Error in GetStatusForGUI: " + str(e1))

        return Status

    #---------------------CustomController::DisplayLogs-------------------------
    def DisplayLogs(self, AllLogs = False, DictOut = False, RawOutput = False):

        RetValue = collections.OrderedDict()
        LogList = []
        RetValue["Logs"] = LogList
        UnknownFound = False

        # Not supported

        return RetValue

    #------------ CustomController::DisplayMaintenance -------------------------
    def DisplayMaintenance (self, DictOut = False, JSONNum = False):

        try:
            # use ordered dict to maintain order of output
            # ordered dict to handle evo vs nexus functions
            Maintenance = collections.OrderedDict()
            Maintenance["Maintenance"] = []

            if not self.ControllerDetected or not self.InitComplete:
                Maintenance["Maintenance"].append({"Genmon State" : "Waiting for comms"})
                if not DictOut:
                    return self.printToString(self.ProcessDispatch(Maintenance,""))
                return Maintenance

            Maintenance["Maintenance"].append({"Model" : self.Model})
            Maintenance["Maintenance"].append({"Controller Detected" : self.GetController()})
            Maintenance["Maintenance"].append({"Nominal RPM" : self.NominalRPM})
            Maintenance["Maintenance"].append({"Rated kW" : self.NominalKW})
            Maintenance["Maintenance"].append({"Nominal Frequency" : self.NominalFreq})
            Maintenance["Maintenance"].append({"Fuel Type" : self.FuelType})

            Maintenance["Maintenance"].extend( self.GetDisplayList(self.controllerimport, "maintenance"))

            Maintenance = self.DisplayMaintenanceCommon(Maintenance, JSONNum = JSONNum)

        except Exception as e1:
            self.LogErrorLine("Error in DisplayMaintenance: " + str(e1))

        if not DictOut:
            return self.printToString(self.ProcessDispatch(Maintenance,""))

        return Maintenance

    #------------ CustomController::DisplayStatus ------------------------------
    def DisplayStatus(self, DictOut = False, JSONNum = False):

        try:


            Status = collections.OrderedDict()
            Status["Status"] = []

            if not self.ControllerDetected or not self.InitComplete:
                Status["Status"].append({"Genmon State" : "Waiting for comms"})
                if not DictOut:
                    return self.printToString(self.ProcessDispatch(Status,""))
                return Status

            gen_status = self.GetSwitchState()
            if gen_status != "Unknown":
                Status["Status"].append({"Switch State" : gen_status})

            gen_status = self.GetEngineState()
            if gen_status != "Unknown":
                Status["Status"].append({"Engine State" : gen_status})

            gen_status = self.GetGeneratorStatus()
            if gen_status != "Unknown":
                Status["Status"].append({"Generator Status" : gen_status})

            Status["Status"].extend(self.GetDisplayList(self.controllerimport, "status"))

            if self.SystemInAlarm():
                Status["Status"].append({"Alarm State" : "System In Alarm"})
                Status["Status"].append({"Active Alarms" : self.GetExtendedDisplayString(self.controllerimport, "alarm_conditions")})

            Status = self.DisplayStatusCommon(Status, JSONNum = JSONNum)

            # Generator time
            Time = []
            Status["Status"].append({"Time":Time})
            Time.append({"Monitor Time" : datetime.datetime.now().strftime("%A %B %-d, %Y %H:%M:%S")})
            # TODO Time.append({"Generator Time" : self.GetDateTime()})

        except Exception as e1:
            self.LogErrorLine("Error in DisplayStatus: " + str(e1))

        if not DictOut:
            return self.printToString(self.ProcessDispatch(Status,""))

        return Status

    #------------ CustomController:GetSingleSensor -----------------------------
    def GetSingleSensor(self, dict_name, ReturnFloat = False, ReturnInt = False):

        try:
            if ReturnInt:
                ReturnValue = 0
            elif ReturnFloat:
                ReturnValue = 0.0
            else:
                ReturnValue = ""
            dict_results = self.controllerimport.get(dict_name, None)

            if dict_results == None:
                return ReturnValue

            if ReturnInt or ReturnFloat:
                no_units = True
            else:
                no_units = False
            out_string = self.GetExtendedDisplayString(self.controllerimport, dict_name)

            if not len(out_string):
                return ReturnValue
            if ReturnInt or ReturnFloat:
                out_string = self.removeAlpha(out_string)
            if ReturnInt:
                if self.StringIsFloat(out_string):
                    return int(float(out_string))
                return int(out_string)
            elif ReturnFloat:
                if self.StringIsInt(out_string):
                    return float(int(out_string))
                return float(out_string)
            else:
                return out_string

        except Exception as e1:
            self.LogErrorLine("Error in GetSingleSensor: " + str(dict_name) +  " : " + str(e1))
            return "Unknown"
    #------------ GeneratorController:GetExtendedDisplayString -----------------
    # returns one or multiple status strings
    def GetExtendedDisplayString(self, inputdict, key_name, no_units = False):

        try:
            StateList =  self.GetDisplayList(inputdict, key_name, no_units = no_units)
            ListValues = []
            for entry in StateList:
                ListValues.extend(entry.values())
            ReturnString = ",".join(ListValues)
            if not len(ReturnString):
                return "Unknown"
            return ReturnString
        except Exception as e1:
            self.LogErrorLine("Error in DisplayStatus: " + str(e1))
            return "Unknown"

    #------------ GeneratorController:GetGaugeValue ----------------------------
    def GetGaugeValue(self, sensor_title):

        try:
            sensor_list = self.GetDisplayList(self.controllerimport, "gauges", no_units = True)

            for sensor in sensor_list:
                if sensor_title in list(sensor.keys()):
                    items = list(sensor.values())
                    if len(items) == 1:
                        return items[0]
            return None
        except Exception as e1:
            self.LogErrorLine("Error in GetGaugeValue: " + str(e1))
            return None
    #------------ GeneratorController:GetDisplayList ---------------------------
    # parse a list of modbus values (expressed as dicts) and any sub lists of
    # values (also expressed as dicts, return a displayable dict with parsed values
    def GetDisplayList(self, inputdict, key_name, JSONNum = False, no_units = False):

        ReturnValue = []
        try:
            default = None
            ParseList = inputdict.get(key_name, None)
            if not isinstance(ParseList, list) or ParseList == None:
                self.LogDebug("Error in GetDisplayList: invalid input or data: " + str(key_name))
                return ReturnValue

            for Entry in ParseList:
                if not isinstance(Entry, dict):
                    self.LogError("Error in GetDisplayList: invalid list entry: " + str(Entry))
                    return ReturnValue

                title, value = self.GetDisplayEntry(Entry, JSONNum, no_units = no_units)

                if title == "default":
                    default = value
                    value = None
                if title != None:
                    if value != None:
                        ReturnValue.append({title:value})

            if not len(ReturnValue) and not default == None:
                ReturnValue.append({"default":default})
        except Exception as e1:
            self.LogErrorLine("Error in GetDisplayList: (" + key_name + ") : " + str(e1))
            return ReturnValue
        return ReturnValue

    #-------------CustomController:GetButtons-----------------------------------
    def GetButtons(self):
        try:
            button_list = self.controllerimport.get("buttons", None)

            if button_list == None:
                return {}
            if not isinstance(button_list, list):
                self.LogDebug("Error in GetButtons: invalid input or data: " + str(type(button_list)))
                return {}

            return_buttons = {}
            for button in button_list:
                return_buttons[button["onewordcommand"]] = button["title"]
            return return_buttons

        except Exception as e1:
            self.LogErrorLine("Error in GetButtons: " + str(e1))
            return {}

    #----------  CustomController::SetGeneratorRemoteCommand--------------------
    # CmdString will be in the format: "setremote=start"
    # valid commands are defined in the JSON file
    # return string "Remote command sent successfully" or some descriptive error
    # string if failure
    def SetGeneratorRemoteCommand(self, CmdString):
        try:

            try:
                #Format we are looking for is "setremote=start"
                CmdList = CmdString.split("=")
                if len(CmdList) != 2:
                    self.LogError("Validation Error: Error parsing command string in SetGeneratorRemoteCommand (parse): " + CmdString)
                    return "Error"

                CmdList[0] = CmdList[0].strip()

                if not CmdList[0].lower() == "setremote":
                    self.LogError("Validation Error: Error parsing command string in SetGeneratorRemoteCommand (parse2): " + CmdString)
                    return "Error"

                Command = CmdList[1].strip()
                Command = Command.lower()

            except Exception as e1:
                self.LogErrorLine("Validation Error: Error parsing command string in SetGeneratorRemoteCommand: " + CmdString)
                self.LogError( str(e1))
                return "Error"

            button_list = self.controllerimport.get("buttons", None)

            if button_list == None:
                return "No buttons defined"
            if not isinstance(button_list, list):
                self.LogDebug("Error in SetGeneratorRemoteCommand: invalid input or data: " + str(type(button_list)))
                return "Malformed button in JSON file."

            for button in button_list:
                if button["onewordcommand"].lower() == Command.lower():
                    command_sequence = button["command_sequence"]
                    if not len(command_sequence):
                        self.LogDebug("Error in SetGeneratorRemoteCommand: invalid command sequence")
                        continue

                    with self.ModBus.CommAccessLock:
                        for command in command_sequence:
                            if not len(command["value"]):
                                self.LogDebug("Error in SetGeneratorRemoteCommand: invalid value array")
                                continue
                            if isinstance(command["value"], list):
                                if not (len(command["value"]) % 2) == 0:
                                    self.LogDebug("Error in SetGeneratorRemoteCommand: invalid value length")
                                    return "Command not found."
                                Data = []
                                for item in command["value"]:
                                    if isinstance(item, str):
                                        Data.append(int(item, 16))
                                    elif isinstance(item, int):
                                        Data.append(item)
                                    else:
                                        self.LogDebug("Error in SetGeneratorRemoteCommand: invalid type if value list")
                                        return "Command not found."
                                self.LogDebug("Write: " + command["reg"] + ": " + str(Data))
                                self.ModBus.ProcessWriteTransaction(command["reg"], len(Data) / 2, Data)

                            elif isinstance(command["value"], str):
                                value = int(command["value"], 16)
                                LowByte = value & 0x00FF
                                HighByte = value >> 8
                                Data= []
                                Data.append(HighByte)           # Value for indexed register (High byte)
                                Data.append(LowByte)            # Value for indexed register (Low byte)
                                self.LogDebug("Write: " + command["reg"] + ": " + ("%x %x" % (HighByte, LowByte)))
                                self.ModBus.ProcessWriteTransaction(command["reg"], len(Data) / 2, Data)
                            elif isinstance(command["value"], int):
                                value = command["value"]
                                LowByte = value & 0x00FF
                                HighByte = value >> 8
                                Data= []
                                Data.append(HighByte)           # Value for indexed register (High byte)
                                Data.append(LowByte)            # Value for indexed register (Low byte)
                                self.LogDebug("Write: " + command["reg"] + ": " + ("%x %x" % (HighByte, LowByte)))
                                self.ModBus.ProcessWriteTransaction(command["reg"], len(Data) / 2, Data)
                            else:
                                self.LogDebug("Error in SetGeneratorRemoteCommand: invalid value type")
                                return "Command not found."

                    return "Remote command sent successfully"

        except Exception as e1:
            self.LogErrorLine("Error in SetGeneratorRemoteCommand: " + str(e1))
            return "Error"
        return "Command not found."

    #------------ GeneratorController:GetDisplayEntry --------------------------
    # return a title and value of an input dict describing the modbus register
    # and type of value it is
    def GetDisplayEntry(self, entry, JSONNum = False, no_units = False):

        ReturnTitle = ReturnValue = None
        try:
            if not isinstance(entry, dict):
                self.LogError("Error: non dict passed to GetDisplayEntry: " + str(type(entry)))
                return ReturnTitle, ReturnValue

            if 'reg' not in entry.keys() and entry["type"] != "list":  # required
                self.LogError("Error: reg not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            elif entry["type"] != "list" and not self.StringIsHex(entry['reg']):
                self.LogError("Error: reg does not contain valid hex value in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if not "type" in entry:  # required
                self.LogError("Error: type not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if not "title" in entry:  # required
                self.LogError("Error: title not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if entry["type"] == "bits" and not "value" in entry:
                self.LogError("Error: value (requried for bits) not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if entry["type"] == "bits" and not "text" in entry:
                self.LogError("Error: text not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if entry["type"] == "float" and not "multiplier" in entry:
                self.LogError("Error: multiplier (requried for float) not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if entry["type"] == "regex" and not "regex" in entry:
                self.LogError("Error: regex not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if "multiplier" in entry and entry["multiplier"] == 0:
                self.LogError("Error: multiplier (requried for float) must not be zero in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if entry["type"] in ["int", "bits", "regex"] and not "mask" in entry:  # required
                self.LogError("Error: mask not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            elif "mask" in entry and not self.StringIsHex(entry['mask']):
                self.LogError("Error: mask does not contain valid hex value in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue
            if entry["type"] == "default" and not "text" in entry:
                self.LogError("Error: text (default) not found in input to GetDisplayEntry: " + str(entry))
                return ReturnTitle, ReturnValue

            if entry["type"] != "list" and entry["reg"] not in self.Registers:
                # have not read the needed register yet
                return ReturnTitle, ReturnValue
            ReturnTitle = entry["title"]
            if entry["type"] == "bits":
                value = self.GetParameter(entry["reg"], ReturnInt = True)
                value = value & int(entry["mask"], 16)
                if value == int(entry["value"], 16):
                    ReturnValue = entry["text"]
                else:
                    ReturnValue = None
                    return ReturnTitle, ReturnValue
            elif entry["type"] == "float":
                Divider = 1 / float(entry["multiplier"])
                value = self.ConvertValue(entry, self.GetParameter(entry["reg"], Divider = Divider, ReturnFloat = True))
                ReturnValue = float(value)
            elif entry["type"] == "int":
                value = self.GetParameter(entry["reg"], ReturnInt = True)
                value = value & int(entry["mask"], 16)
                if "multiplier" in entry:
                    value = value * float(entry["multiplier"])
                ReturnValue = int(self.ConvertValue(entry, value))
            elif entry["type"] == "regex":
                regex_pattern = entry["regex"]
                value = self.GetParameter(entry["reg"], ReturnInt = True)
                value = value & int(entry["mask"], 16)
                value = "%x" % value
                result = re.match(regex_pattern, value)

                if result:
                    ReturnValue = entry["text"]
                else:
                    ReturnValue = None
            elif entry["type"] == "list":
                list_entry = entry["value"]
                separator = ""
                if "separator" in entry:
                    separator = entry["separator"]
                value_list = []
                for item in list_entry:
                    title, value = self.GetDisplayEntry(item)
                    if value != None:
                        value_list.append(str(self.FormatEntry(item, value)))
                ReturnValue = separator.join(value_list)
            elif entry["type"] == "default":
                ReturnValue = entry["text"]
                ReturnTitle = "default"
            else:
                self.LogError("Unknown type found in GetDisplayEntry: " + str(entry))


            if not no_units and "units" in entry and ReturnValue != None:
                units = entry["units"]
                if units == None:
                    units = ""
                ReturnValue = self.ValueOut(ReturnValue, str(units), JSONNum)

        except Exception as e1:
            self.LogErrorLine("Error in GetDisplayEntry : " + str(e1))

        return ReturnTitle, ReturnValue

    #------------ GeneratorController:ConvertValue ----------------------------- 
    def ConvertValue(self, entry, value):
        try:
            if "temperature" in entry:
                if not self.UseMetric and entry["temperature"].lower() == "celsius": 
                    return self.ConvertCelsiusToFahrenheit(value)
                elif self.UseMetric and entry["temperature"].lower() == "fahrenheit":
                    return self.ConvertFahrenheitToCelsius(value)
                else:
                    return value
            else:
                return value
        except Exception as e1:
            self.LogErrorLine("Error in FormatEntry : " + str(e1))
            return value
    #------------ GeneratorController:FormatEntry ------------------------------ 
    def FormatEntry(self, entry, value):
        try:
            if "format" in entry:
                if entry["type"] == "float":
                    return str(entry["format"] % float(value))
                elif entry["type"] == "int":
                    return str(entry["format"] % int(value))                    
                else:
                    return value
            else:
                return value
        except Exception as e1:
            self.LogErrorLine("Error in FormatEntry : " + str(e1))
            return value

    #------------ GeneratorController:GetRunHours ------------------------------
    # return a string with no units of run hours
    def GetRunHours(self):
        try:
            ReturnValue, run_hours = self.GetSingleEntry("run_hours")
            if not ReturnValue:
                return "0"
            run_hours = self.removeAlpha(str(run_hours))
            return run_hours
        except Exception as e1:
            self.LogErrorLine("Error in GetRunHours : " + str(e1))
            return "0"

    #------------------- CustomController::DisplayOutage -----------------------
    def DisplayOutage(self, DictOut = False, JSONNum = False):

        try:

            Outage = collections.OrderedDict()
            Outage["Outage"] = []

            if not self.OutageSupported:
                Outage["Outage"].append({"Status" : "No Supported"})
                if not DictOut:
                    return self.printToString(self.ProcessDispatch(Outage,""))
                return Outage

            if self.SystemInOutage:
                outstr = "System in outage since %s" % self.OutageStartTime.strftime("%Y-%m-%d %H:%M:%S")
            else:
                if self.ProgramStartTime != self.OutageStartTime:
                    OutageStr = str(self.LastOutageDuration).split(".")[0]  # remove microseconds from string
                    outstr = "Last outage occurred at %s and lasted %s." % (self.OutageStartTime.strftime("%Y-%m-%d %H:%M:%S"), OutageStr)
                else:
                    outstr = "No outage has occurred since program launched."

            Outage["Outage"].append({"Status" : outstr})
            Outage["Outage"].append({"System In Outage" : "Yes" if self.SystemInOutage else "No"})

             # get utility voltage
            
            bSuccess, UtilityVoltage = self.GetSingleEntry("linevoltage")
            if bSuccess:
                Outage["Outage"].append({"Utility Voltage" : self.ValueOut(UtilityVoltage, "V", JSONNum)})
            Outage["Outage"].append({"Utility Voltage Minimum" : self.ValueOut(self.UtilityVoltsMin, "V", JSONNum)})
            Outage["Outage"].append({"Utility Voltage Maximum" : self.ValueOut(self.UtilityVoltsMax, "V", JSONNum)})

            bSuccess, ThresholdVoltage = self.GetSingleEntry("thresholdvoltage")
            if bSuccess:
                Outage["Outage"].append({"Utility Threshold Voltage" : self.ValueOut(int(ThresholdVoltage), "V", JSONNum)})

            bSuccess, PickupVoltage = self.GetSingleEntry("pickupvoltage")
            if bSuccess:
                Outage["Outage"].append({"Utility Pickup Voltage" : self.ValueOut(int(PickupVoltage), "V", JSONNum)})

            Outage["Outage"].append({"Outage Log" : self.DisplayOutageHistory()})

        except Exception as e1:
            self.LogErrorLine("Error in DisplayOutage: " + str(e1))

        if not DictOut:
            return self.printToString(self.ProcessDispatch(Outage,""))

        return Outage

    #------------ CustomController::DisplayRegisters ---------------------------
    def DisplayRegisters(self, AllRegs = False, DictOut = False):

        try:
            Registers = collections.OrderedDict()
            Regs = collections.OrderedDict()
            Registers["Registers"] = Regs

            RegList = []

            Regs["Num Regs"] = "%d" % len(self.Registers)

            Regs["Base Registers"] = RegList
            # display all the registers
            temp_regsiters = self.Registers
            for Register, Value in temp_regsiters.items():
                RegList.append({Register:Value})


        except Exception as e1:
            self.LogErrorLine("Error in DisplayRegisters: " + str(e1))

        if not DictOut:
            return self.printToString(self.ProcessDispatch(Registers,""))

        return Registers

    #----------  CustomController:GetController  -------------------------------
    # return the name of the controller, if Actual == False then return the
    # controller name that the software has been instructed to use if overridden
    # in the conf file
    def GetController(self, Actual = True):

        return self.Model

    #----------  CustomController:ComminicationsIsActive  ----------------------
    # Called every few seconds, if communictions are failing, return False, otherwise
    # True
    def ComminicationsIsActive(self):
        if self.LastRxPacketCount == self.ModBus.RxPacketCount:
            return False
        else:
            self.LastRxPacketCount = self.ModBus.RxPacketCount
            return True

    #----------  CustomController:RemoteButtonsSupported  ----------------------
    # return true if Panel buttons are settable via the software
    def RemoteButtonsSupported(self):
        return False
    #----------  CustomController:PowerMeterIsSupported  -----------------------
    # return true if GetPowerOutput is supported
    def PowerMeterIsSupported(self):

        if self.bDisablePowerLog:
            return False
        if self.UseExternalCTData:
            return True

        if "power" in self.controllerimport.keys():
            return True
        return False

    #---------------------CustomController::GetPowerOutput----------------------
    # returns current kW
    # rerturn empty string ("") if not supported,
    # return kW with units i.e. "2.45kW"
    def GetPowerOutput(self, ReturnFloat = False):

        try:
            if ReturnFloat:
                DefaultReturn = 0.0
            else:
                DefaultReturn = "0 kW"

            if not self.PowerMeterIsSupported():
                return DefaultReturn

            ReturnValue = self.CheckExternalCTData(request = 'power', ReturnFloat = ReturnFloat)
            if ReturnValue !=  None:
                return ReturnValue

            bSuccess, PowerValue = self.GetSingleEntry("power")
            if not bSuccess or PowerValue == None:
                return DefaultReturn
            if ReturnFloat:
                return float(PowerValue)
            return PowerValue
            
        except Exception as e1:
            self.LogErrorLine("Error in GetPowerOutput: " + str(e1))
            return "Unknown"

    #------------ CustomController:CheckExternalCTData -------------------------
    def CheckExternalCTData(self, request = 'current', ReturnFloat = False, gauge = False):
        try:

            if ReturnFloat:
                DefaultReturn = 0.0
            else:
                DefaultReturn = 0

            if not self.UseExternalCTData:
                return None
            ExternalData = self.GetExternalCTData()

            if ExternalData == None:
                return None

            # This assumes the following format:
            # NOTE: all fields are *optional*
            # { "strict" : True or False (true requires an outage to use the data)
            #   "current" : optional, float value in amps
            #   "power"   : optional, float value in kW
            #   "powerfactor" : float value (default is 1.0) used if converting from current to power or power to current
            #   ctdata[] : list of amps for each leg
            #   ctpower[] :  list of power in kW for each leg
            #   voltage : optional, float value of total RMS voltage (all legs combined)
            #   phase : optional, int (1 or 3)
            # }
            strict = False
            if 'strict' in ExternalData:
                strict = ExternalData['strict']

            if strict:
                if not self.SystemInOutage:
                    if gauge:
                        return DefaultReturn
                    else:
                        return None

            # if we get here we must convert the data.
            if not "outputvoltage" in self.controllerimport.keys():
                self.LogDebug("WARNING: no outputvoltage in custom controller defintion")
                Voltage = None
            else:
                bSuccess, Voltage =  self.GetSingleEntry("outputvoltage")
                if not bSuccess:
                    return DefaultReturn

            if isinstance(Voltage, str):
                # TODO why is this needed?
                Voltage = int(self.removeAlpha(Voltage))

            return self.ConvertExternalData(request = request, voltage = Voltage, ReturnFloat = ReturnFloat)

        except Exception as e1:
            self.LogErrorLine("Error in CheckExternalCTData: " + str(e1))
            return DefaultReturn

    #------------ CustomController:GetBaseStatus -------------------------------
    # return one of the following: "ALARM", "SERVICEDUE", "EXERCISING", "RUNNING",
    # "RUNNING-MANUAL", "OFF", "MANUAL", "READY"
    def GetBaseStatus(self):
        try:
            EngineStatus = self.GetEngineState().lower()
            GeneratorStatus = self.GetGeneratorStatus().lower()
            SwitchState = self.GetSwitchState().lower()

            if "running" in EngineStatus:
                IsRunning = True
            else:
                IsRunning = False
            if "stopped" in GeneratorStatus:
                IsStopped = True
            else:
                IsStopped = False

            ExerciseList = ["exercising", "exercise", "quiettest", "test"]
            if any(x in EngineStatus for x in ExerciseList) or any(x in GeneratorStatus for x in ExerciseList) or any(x in SwitchState for x in ExerciseList):
                IsExercising = True
            else:
                IsExercising = False
            if "service" in EngineStatus or "service" in GeneratorStatus:
                ServiceDue = True
            else:
                ServiceDue = False

            if self.SystemInAlarm():
                return "ALARM"
            elif ServiceDue:
                return "SERVICEDUE"
            elif IsExercising:
                return "EXERCISING"
            elif IsRunning and SwitchState.startswith("auto"):
                return "RUNNING"
            elif IsRunning and SwitchState.startswith("manual"):
                return "RUNNING-MANUAL"
            elif SwitchState.startswith("manual"):
                return "MANUAL"
            elif SwitchState.startswith("auto"):
                return "READY"
            elif SwitchState == "off":
                return "OFF"
            else:
                if self.InitComplete:
                    message = "Unknown Base State: " + str(EngineStatus) + ": " + str(GeneratorStatus) + ": " + str(SwitchState)
                    self.FeedbackPipe.SendFeedback("Base State", FullLogs = True, Always = True, Message = message)
                return "UNKNOWN"
        except Exception as e1:
            self.LogErrorLine("Error in GetBaseStatus: " + str(e1))
            return "UNKNOWN"

    #----------  CustomController::FuelSensorSupported--------------------------
    def FuelSensorSupported(self):

        if "fuel" in self.controllerimport.keys():
            return True

        return False

    #------------ CustomController:GetFuelSensor -------------------------------
    def GetFuelSensor(self, ReturnInt = False):

        if not self.FuelSensorSupported():
            return None

        try:
            ReturnVal, FuelValue = self.GetSingleEntry("fuel")
            if not ReturnVal or FuelValue == None:
                return None
            if ReturnInt:
                return int(FuelValue)
            return FuelValue
        except Exception as e1:
            self.LogErrorLine("Error in GetFuelSensor: " + str(e1))
            return None

    #----------  CustomController::GetFuelConsumptionDataPoints-----------------
    def GetFuelConsumptionDataPoints(self):

        try:
            if self.FuelHalfRate == 0 or self.FuelFullRate == 0:
                return None

            return [.5, float(self.FuelHalfRate), 1.0, float(self.FuelFullRate), self.FuelUnits]

        except Exception as e1:
            self.LogErrorLine("Error in GetFuelConsumptionDataPoints: " + str(e1))
        return None
