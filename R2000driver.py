'''
This library reads out the OMD10M-R2000 sensor.

created by: Fabian Heinemann
contact: f.heinemann@mailbox.tu-berlin.de
'''

'''
************************************************************************
imports which are neccessary for the library to run
************************************************************************
'''
# math module
import math
# communication over http get 
import urllib2
# socket module to get the sensor data
import socket
# transfer data from and to byte string
import struct
# json implentation in python
import json
# usefull libraries for system interaction and file read/write
import sys, os

# I don't know why but I think this is neccessary for matplotlib
# something...
sys.ps1 = 'SOMETHING'
# time to get the current timestamp
import time
# regular expressions
import re
# traceback for error analysis
import traceback as tb
# multiprocessing and data sharing between processes
from multiprocessing import Process, Value
from multiprocessing.managers import BaseManager
# ploting
import matplotlib.pyplot as plt

plt.ion()

'''
************************************************************************
usefull variables
************************************************************************
'''

# parameter list: these parameters are specified in the documentation
parameter_list = ["vendor", "product", "part", "serial", "revision_fw",
                  "revision_hw", "max_connections", "feature_flags",
                  "radial_range_min", "radial_range_max", "ip_address",
                  "radial_resolution", "angular_fov", "scan_frequency",
                  "angular_resolution", "ip_mode", "samples_per_scan",
                  "subnet_mask", "gateway", "scan_frequency_measured",
                  "scan_direction", "hmi_language", "load_indication",
                  "status_flags", "user_notes", "ip_mode_current",
                  "device_family", "mac_address", "subnet_mask_current",
                  "hmi_display_mode", "hmi_button_lock", "user_tag",
                  "ip_address_current", "gateway_current",
                  "system_time_raw", "locator_indication"]

# parameter list of the status message
parameter_status = ["status_flags", "load_indication", "up_time",
                    "system_time_raw", "power_cycles", "operation_time",
                    "operation_time_scaled", "temperature_current",
                    "temperature_min", "temperature_max",
                    "contamination"]

# parameter list of the scan message
parameter_scan = ["address", "port", "watchdog", "watchdogtimeout",
                  "packet_type", "start_angle", "max_num_points_scan"]

# status codes for the http communication
http_status_codes = {200: "OK request successfully received",
                     400: "Bad Request wrong URI syntax",
                     403: "Forbidden permission denied for this URI",
                     404: "Not Found unknown command code or URI",
                     405: "Method not allowed invalid requested" \
                          + " (currently only GET is allowed)"}

'''
************************************************************************
usefull classes
************************************************************************
'''


class Logger():
    '''
    this class is the base class for all other classes 
    defines the verbosity level and therefor what messages 
    will be printed
    by default vLevel is set to Zero
    '''

    def __init__(self):
        '''
        constructor of the Logger class:
        defines the text for the info text for the log messages 
        and the vLevel
        '''
        self.vMsg = {0: "INFO    ", 1: "DEBUG   ",
                     2: "WARNING ", 3: "ERROR   "}
        # change the verbosity level here
        self.vLevel = 0

    def vLog(self, l, *msgs):
        '''
        log methode to display helpfull or neccessary logs
        the vLevel defines which message will be shown
        @param[in] l log message level
        @param[in] msgs list of messages
        '''
        if l >= self.vLevel and l <= 3:
            msg = ""
            for m in msgs:
                msg += str(m) + "; "
            print(self.vMsg[l] + msg)
        else:
            print("v_level %s not recognised. output: %s" % (l, msg))


class Header(object):
    '''
    class that defines the header of a message which comes 
    from the sensor
    the structure is given by the documentation 
    '''

    def __iter__(self):
        '''
        lets the class be castable to a dict
        this is just for print and display resons
        '''
        for attr, value in self.__dict__.iteritems():
            yield attr, value

    def __init__(self, msg):
        '''
        constructor of the header class
        for any information on the specific field refer to the 
        official documentation of the R2000
        @param[in] msg header message recieved from the sensor
        '''
        self.msg = msg
        if not self.msg:
            return None
        self.magic = msg[0]
        self.packet_type = msg[1]
        self.packet_size = msg[2]
        self.header_size = msg[3]
        self.scan_number = msg[4]
        self.packet_number = msg[5]
        self.timestamp_raw = msg[6]
        self.timestamp_sync = msg[7]
        # status_flags got there own parsing method
        self.scan_frequency = msg[9]
        self.num_points_scan = msg[10]
        self.num_points_packet = msg[11]
        self.first_index = msg[12]
        self.first_angle = msg[13]
        self.angular_increment = msg[14]

    @property
    def status_flags(self):
        '''
        this property is just to split the status flaks to 
        their specific values
        for any information on the specific field refer to the 
        official documentation of the R2000
        '''
        if not self.msg:
            return None
        else:
            return {"scan_data_info": bool(self.msg[8] \
                                           & 1 << 31 - 0),
                    "new_settings": bool(self.msg[8] \
                                         & 1 << 31 - 1),
                    "invalid_data": bool(self.msg[8] \
                                         & 1 << 31 - 2),
                    "unstable_rotation": bool(self.msg[8] \
                                              & 1 << 31 - 3),
                    "skipped_packets": bool(self.msg[8] \
                                            & 1 << 31 - 4),
                    "device_warning": bool(self.msg[8] \
                                           & 1 << 31 - 8),
                    "low_temperature_warning": bool(self.msg[8] \
                                                    & 1 << 31 - 10),
                    "high_temperature_warning": bool(self.msg[8] \
                                                     & 1 << 31 - 11),
                    "device_overload": bool(self.msg[8] \
                                            & 1 << 31 - 12),
                    "device_error": bool(self.msg[8] \
                                         & 1 << 31 - 16),
                    "low_temperature_error": bool(self.msg[8] \
                                                  & 1 << 31 - 18),
                    "low_temperature_error": bool(self.msg[8] \
                                                  & 1 << 31 - 19),
                    "device_overload": bool(self.msg[8] \
                                            & 1 << 31 - 20),
                    "device_defect": bool(self.msg[8] \
                                          & 1 << 31 - 30)}

    def printHeader(self):
        '''
        prints the header
        '''
        print(dict(self))


class DataBuffer(object):
    '''
    DataBuffer class which defines how the data will be handelt 
    between different processes
    '''

    def __init__(self, samples_per_scan):
        '''
        constructor which need the samples per scan to define 
        the number of packages
        the header, distance and amplude buffers are reserved
        @param[in] samples_per_scan number of samples per scan (for one sensor sweep)
        '''
        pac_num = samples_per_scan / 336 + 1
        self.header = [None] * pac_num
        self.distance = [list()] * pac_num
        self.amplitude = [list()] * pac_num

    def add(self, header, distance, amplitude):
        '''
        methode to add data to the specific buffer slot
        the data will be insertet according to the index number of the package
        @param[in] header header of the package
        @param[in] distance distances of the data points to the sensor
        @param[in] amplitude amplitude for each data point of the sensor
        '''
        idx = header.packet_number - 1
        self.header[idx] = header
        self.distance[idx] = distance
        self.amplitude[idx] = amplitude

    def __len__(self):
        '''
        convinient methode to have len() capability
        '''
        a = 0
        for d in self.distance:
            a += len(d)
        return a

    def get(self):
        '''
        get the whole data buffer
        '''
        if self.header or self.distance or self.amplitude:
            d = list()
            map(d.extend, self.distance)
            a = list()
            map(a.extend, self.amplitude)
            return self.header, d, a
        else:
            return None


class DataManager(BaseManager):
    '''
    convinient class to enable the manager capability of the 
    multiprocessing module
    '''
    pass


# this assignment is needed
DataManager.register("DataBuffer", DataBuffer)

'''
************************************************************************
the driver class
************************************************************************
'''


class R2000Driver(object, Logger):
    '''
    R2000Driver class which defines all methods neccessary for the 
    communication from and to the sensor
    these methods are build according the official documentation
    '''

    def __init__(self, sensor_ip, port=50001, address=None,
                 packet_type='C', start_angle=-1800000,
                 real=True):
        '''
        constructor of the driver class, initialize connection to the sensor and defines some usefull variables
        @param[in] sensor_ip ip address of the sensor
        @param[in] port port the sensor should open (default 50001)
        @param[in] address ip address of the client
        @param[in] packet_type type of the packet send from the sensor (only C supported)
        @param[in] start_angle start angle of the scan field
        @param[in] real flag which shows if the sensor is real or a dummy sensor is used
        '''
        # init the base class
        Logger.__init__(self)
        # is it a real sensor or software dummy sensor?
        self.real = real
        # signals if the process is running
        self.is_running = Value('i', 0)
        # get the senosr IP
        if self.real:
            self.sensor_ip = sensor_ip
        else:
            self.sensor_ip = sensor_ip.split(':')[0]
            self.sensor_port = sensor_ip.split(':')[1]
        self.param = dict()
        # port for the connection
        self.param["port"] = str(port)
        # ip of the client (probably the ip, the script is running on)
        self.param["address"] = str(address)
        # packet type of the return message (see dokumentation)
        self.param["packet_type"] = str(packet_type)
        # start angle when scanning
        self.param["start_angle"] = str(start_angle)
        # process list
        self.process = list()
        # look if sensor is online
        if os.system("ping -c 1 " + self.sensor_ip + \
                     "> /dev/null 2>&1"):
            self.vLog(3, "Sensor at %s is not online" % (self.sensor_ip))
            sys.exit(0)
        # set init configuration
        self.samples_per_scan = 2400
        param = dict()
        param["scan_frequency"] = 35
        param["samples_per_scan"] = self.samples_per_scan
        self.setParameter(param)

        # databuffer initialisation
        self.manager = DataManager()
        self.manager.start()
        self.data = self.manager.DataBuffer(self.samples_per_scan)

    # **************************START PRIVATE METHODS*******************

    def __sendRequest(self, request, parameters=None):
        '''
        method that sends the requests to the sensor over http
        the structure of the http uri is defined in the documentation
        @param[in] request request to be send to the sensor
        @param[in] parameters parameter string
        @return response in a dict or None if an error appears
        '''
        # append the request
        if self.real:
            msg = "http://" + self.sensor_ip + "/cmd/" + request
        else:
            msg = "http://" + self.sensor_ip + ':' + \
                  self.sensor_port + "/" + request
        # append the parameters
        if parameters != None:
            msg += '?' + parameters
        # log the message
        self.vLog(1, msg)
        # send the message to the sensor
        try:
            response = urllib2.urlopen(msg).read()
            # parse response
            return self.__parseHTTPResponse(response)
        except urllib2.HTTPError as e:
            # search for the status code and read the according message
            e_code = int(re.search(r'\d+', str(e)).group())
            self.vLog(3, http_status_codes[e_code])
            return

    def __parseHTTPResponse(self, response):
        '''
        parse the response of the http get message
        @param[in] response http response from the command query (see sendRequest)
        @return returns the response as json decoded dict
        '''
        # parse the jason code into a dict
        resp = json.loads(response)
        # look for error codes
        if resp["error_code"] != 0:
            self.vLog(3, resp["error_text"])
        return resp

    def __dataAcquisition(self, tcp, is_running):
        '''
        opens a socket and recieves the data send from the sensor
        @param[in] tcp if true use tcp else udp
        @param[in] ir_running shared memmory kill flag to stop the process
        '''
        # socket
        s = None
        if self.real:
            # tcp or udp socket for the real sensor
            s = socket.socket(socket.AF_INET,
                              socket.SOCK_STREAM if tcp \
                                  else socket.SOCK_DGRAM)
            s.settimeout(0.01)
            s.connect((self.sensor_ip, self.param["port"]))

        else:
            # unix socket for the software dummy sensor
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(0.01)
            s.connect("./.sock_" + str(self.handle))

        # start time
        t = time.time()
        self.vLog(0, "Start Scanning")
        try:
            while is_running.value:
                # reset Watchdog every 30s
                if time.time() - t > 30:
                    self.feedWatchdog(self.handle)
                    t = time.time()
                # recieve the data
                try:
                    data = s.recv(4096)
                    if not data:
                        continue
                except socket.timeout as e:
                    continue
                # handle the data
                if self.__dataHandling(data):
                    self.vLog(3, "Data connection lost")
                    s.close()
                    return
        except:
            self.vLog(3, sys.exc_info()[0])
            tb.print_tb(sys.exc_info()[2])
        finally:
            s.close()
            return

    def __dataHandling(self, data):
        '''
        handle the recieved data
        @param[in] data data package from the sensor
        @return True if there is an error else False
        '''
        try:
            # unfold the header
            # see documentation for header information
            header = Header(struct.unpack('HHIHHHQQIIHHHii', data[:56]))
            # payload length
            pl_len = (header.packet_size - header.header_size) / 4
            # sort out unwanted messages
            if pl_len * 4 != len(data[header.header_size: \
                    header.packet_size]):
                if self.real:
                    self.vLog(1, "Wrong message recieved")
                return False
            # unfold the payload
            payload = struct.unpack('I' * pl_len,
                                    data[header.header_size: \
                                         header.packet_size])

        except:
            self.vLog(3, "Massage skipped with " + \
                      "error %s" % (sys.exc_info()[0]))
            tb.print_tb(sys.exc_info()[2])
            return True

        # see if message is valid
        if header.magic != 41564:
            self.vLog(3, "Message header invalid")
            return True
        # see if package type is valid
        if chr(header.packet_type) not in ['A', 'B', 'C']:
            self.vLog(3, "Unknown packet type")
            return True
        # write the data to the buffer
        dist = list()
        ampl = list()
        for p in payload:
            dist.append(p & int(0x000FFFFF))
            ampl.append((p & int(0xFFFFF000)) >> 20)
        self.data.add(header, dist, ampl)
        return False

    # ****************************END PRIVATE METHODS*******************
    # **************************START PUBLIC METHODS********************

    def startScanning(self, _type="tcp", **kwargs):
        '''
        configure the connection to the sensor with the values given by the constructor
        the parameters can always be changed
        @param[in] _type type of the connection (tcp is default)
        @param[in] kwargs dict of parameters for the tcp connection
        '''
        # use new or default parameters
        for k, v in kwargs.iteritems():
            if k in parameter_scan and bool(v):
                self.param[k] = str(v)
            elif k == "address" and not self.param["address"]:
                self.param["address"] = socket.gethostbyname(
                    socket.gethostname())
            else:
                pass
        # overide package type
        self.param["packet_type"] = 'C'
        ret = None
        if _type == "tcp":
            ret = self.requestHandleTcp(self.param)
        elif _type == "udp":
            ret = self.requestHandleUdb(self.param["address"],
                                        self.param["port"], self.param)
        if "handle" in ret:
            self.handle = ret["handle"]
            f = open('.last_handle', 'w')
            f.write(ret["handle"])
            f.close()
        else:
            try:
                f = open('.last_handle', 'r')
                self.handle = f.read()
                self.stopScanning(pr=False)
                f.close()
            except:
                self.vLog(3, "last_handle not recognised")
            exit(0)

        # check if the desired port was set
        if self.param["port"] != ret["port"]:
            self.param["port"] = ret["port"]
            self.vLog(2, "scanner changed port to: %s" % (ret["port"]))

        if "handle" in ret:
            self.startScanoutput(self.handle)

        # start data acquisition thread
        self.is_running.value = 1
        if _type == "tcp":
            self.process.append(Process(target=self.__dataAcquisition,
                                        args=(True, self.is_running,)))
        else:
            self.process.append(Process(target=self.__dataAcquisition,
                                        args=(False, self.is_running,)))
        self.process[-1].start()

    def start(self):
        '''
        start the sensor
        '''
        try:
            self.startScanoutput(self.handle)
        except:
            pass

    def stop(self):
        '''
        stop the sensor
        '''
        try:
            self.stopScanoutput(self.handle)
        except:
            pass

    def stopScanning(self, pr=True):
        '''
        stops scanning and tries to release the scan handle and kills the process
        @param[in] pr if pr = true kill the process manually else just set the kill flag
        '''
        if self.handle:
            self.stopScanoutput(self.handle)
            time.sleep(.5)
            self.releaseHandle(self.handle)
            time.sleep(.5)
            self.handle = None

        self.is_running.value = 0
        if pr:
            for p in self.process:
                if p.is_alive():
                    try:
                        p.join()
                    except:
                        # process allready dead
                        pass

    def getData(self):
        '''
        returns the gathered data from the shared memory
        @return one complete data_package of the sensor
        '''
        return self.data.get()

    def getSegmentedData(self, from_angle, to_angle, box,
                         dist_box):
        '''
        returns the gathered data and segments it
        @param[in] from_angle angle to start the segmented area
        @param[in] to_angle angle to end the segmented area
        @param[in] box size of the box to catch the objects (e.g. 360x2500mm = [360, 2500])
        @param[in] dist_box distance of the sensor to the beginning of the box
        @return head: head of the data package, distance: distances of the data points to the sensor, amplitude: amplitude of the data point, start_angle_for_display: angle of the first data point, coord: catesian coordinates of the data points
        '''
        # get recorded data from shared memory (see above)
        head, dist, ampl = self.getData()
        # transform the specified from and to angles to an array of ticks 
        angles = sorted([(self.samples_per_scan / 2 - \
                          (a * self.samples_per_scan / 360)) \
                         for a in [from_angle, to_angle]])

        distance = list()
        coord = list()
        amplitude = list()
        # start with the smallest angle
        alpha = (from_angle if from_angle < to_angle else to_angle) * \
                math.pi / 180
        a = list()
        # loop through the distances which are in the angle boundary
        for i, d in enumerate(dist[angles[0]:angles[1]]):
            delta_alpha = i * 2 * math.pi / self.samples_per_scan
            x = d * math.cos(alpha + delta_alpha)
            y = d * math.sin(alpha + delta_alpha)
            # see if value is insite the box -- does not work all the time
            if abs(x) > dist_box and abs(x) < box[1] and abs(y) < box[0] / 2:
                distance.append(d)
                # append segmented values
                coord.append({"x": x, "y": y, "a": alpha + delta_alpha})
                amplitude.append(ampl[angles[0]:angles[1]][i])
                a.append(alpha + delta_alpha)
        if len(a) > 0:
            start_angle_for_display = min(a) * 180 / math.pi
        else:
            start_angle_for_display = 0
        return head, distance, amplitude, start_angle_for_display, coord

    def getDataJson(self):
        '''
        return the gathered data in a json encoded string
        @return json string with coordiantes and average encoded
        '''
        head, dist, ampl, alpha, coord = self.getSegmentedData(-45, 45, [600, 2500], 100)
        ret = {"type": "2dsensor",
               "coordinates": coord,
               "average": self.averageDist(dist)}
        return json.dumps(ret)

    def averageDist(self, distances):
        '''
        return the aveage of the list
        @param[in] distances list of values
        @return average of the input list
        '''
        if len(distances) == 0:
            return 0
        dist = 0.0
        cnt = 0
        for d in distances:
            if dist > 0xFFFFE:
                cnt += 1
            else:
                dist += d
        return dist / (len(distances) - cnt)

    # ****************************END PUBLIC METHODS********************
    # **************************START CONVINIENT METHODS****************
    # use these methods to handle the recorded data
    # ---------------------------------------------

    @property
    def getProtocolInfo(self):
        '''
        returns basic version information on the communication protocol
        parameter name     type         description
        protocol_name      string       Protocol name (currently always ’pfsdp’)
        version_major      uint         Protocol major version (e.g. 1 for ’v1.02’, 3 for ’v3.10’)
        version_minor      uint         Protocol minor version (e.g. 2 for ’v1.02’, 10 for ’v3.10’)
        command_list       string       List of all available HTTP commands
        @return basic version information on the communication protocol
        '''
        return self.__sendRequest("get_protocol_info")

    @property
    def listParameters(self):
        '''
        returns a list of all available global sensor parameters
        @return list of all available global sensor parameters
        '''
        return self.__sendRequest("list_parameters")

    def getParameter(self, param, nr=True, status=False):
        '''
        reads the current value of one or more parameters:
        http://<sensor IP address>/cmd/get_parameter?list=<param1>;<param2>
        @param[in] param list of parameters
        @param[in] nr not reset (if false send reset parameter)
        @param[in] status return status flags instead of parameters 
        '''
        msg = 'list='
        if not param and status:
            param = parameter_status
            nr = True
        elif not param:
            param = parameter_list

        for p in param:
            # check if params are correct
            if p in parameter_list or p in parameter_status:
                msg += p + ';'
            else:
                self.vLog(3, "Parameter: %s is not recognised" % (p))
        # delelte last ;
        msg = msg[:-1]
        return self.__sendRequest(str("get_" if nr else "reset_") \
                                  + "parameter", parameters=msg)

    def setParameter(self, param):
        '''
        Using the command set_parameter the value of any write-accessible parameter can be changed:
        http://<sensor IP address>/cmd/set_parameter?<param1>=<value>&<param2>=<value>
        @param[in] param dict of parameters and values
        '''
        msg = ''
        for p, v in param.iteritems():
            # check if params are correct
            if p in parameter_list:
                msg += p + '=' + str(v) + '&'
            else:
                self.vLog(3, "Parameter: %s is not recognised" % (p))
        # delelte last &
        msg = msg[:-1]
        return self.__sendRequest("set_parameter", parameters=msg)

    def rebootDevice(self):
        '''
        The command reboot_device triggers a soft reboot of the sensor firmware:
        http://<sensor IP address>/cmd/reboot_device
        '''
        self.__sendRequest("reboot_device")

    def resetParameter(self, param):
        '''
        The command reset_parameter resets one or more parameters to the factory default values:
        http://<sensor IP address>/cmd/reset_parameter?list=<param1>;<param2
        @param[in] param list of params to reset
        '''
        return self.getParameter(param, False)

    def requestHandleTcp(self, param, tcp=True):
        '''
        The command request_handle_tcp is used to request a handle for a TCP-based scan data transmission from the sensor
        to the client.  If successful, the client is allowed to create a new TCP connection to the sensor in order to receive scan data.
        Figure 3.5 (of the official documentation) gives an overview on the communication between sensor and client when using an TCP-based channel for scan
        data output.
        @param[in] param list of parameters to configure the tcp connection
        @param[in] tcp if true use tcp connection else udp
        '''
        msg = ''
        for p, v in param.iteritems():
            # check if params are correct
            if p in parameter_scan:
                msg += p + '=' + str(v) + '&'
            else:
                self.vLog(3, "Parameter: %s is not recognised" % (p))
        # delelte last &
        msg = msg[:-1]
        return self.__sendRequest("request_handle_" + \
                                  str("tcp" if tcp else "udp")
                                  , parameters=msg)

    def requestHandleUdp(self, address, port, param):
        '''
        The command request_handle_udp is used to request a handle for an UDP-based scan data transmission from the sensor to
        the client. If successful the sensor will send scan data to the client using the target IP address and UDP port specified at the
        handle request.  Figure  3.4 (of the official documentation) gives an overview on the communication between sensor and client when using an UDP-based
        channel for scan data output.
        @param[in] address address of the sensor
        @param[in] port port, the sensor should open to send the data
        @param[in] param dict of parameters to configure the udp connection
        '''
        param["address"] = address
        param["port"] = port
        return self.requestHandleTcp(param, tcp=False)

    def feedWatchdog(self, handle):
        '''
        The command feed_watchdog feeds the connection watchdog, i.e.  each call of this command resets the watchdog timer.
        Please refer to section 3.2.3 (of the official documentation) for a detailed description of the connection watchdog mechanism.
        @param[in] handle tcp or udp handle
        '''
        msg = "handle=" + handle
        return self.__sendRequest("feed_watchdog"
                                  , parameters=msg)

    def setScanoutputConfig(self, handle, param):
        '''
        Using the command set_scanoutput_config the client can parametrize scan data output separately for each active scan
        data output channel. All command arguments solely apply to the output of scan data. Customization of (global) param-
        eters referring to the recording of measurements (scan data) is done by use of the command set_parameter
        (see section 2.6 (of the official documentation))
        @param[in] handle tcp or udp handle
        @param[in] param dict of parameters and values
        '''
        msg = "handle=" + handle + '&'
        for p, v in param.iteritems():
            # check if params are correct
            if p in parameter_scan:
                msg += p + '=' + str(v) + '&'
            else:
                self.vLog(3, "Parameter: %s is not recognised" % (p))
        # delelte last &
        msg = msg[:-1]
        return self.__sendRequest("set_scanoutput_config"
                                  , parameters=msg)

    def getScanoutputConfig(self, handle, param):
        '''
        The command get_scanoutput_config returns the current scan data output configuration for a specified scan data output
        channel (UDP or TCP).
        @param[in] handle tcp or udp handle
        @param[in] list of parameters
        '''
        msg = "handle=" + handle + '&' + "list="
        for p in param:
            # check if params are correct
            if p in parameter_scan:
                msg += p + ';'
            else:
                self.vLog(3, "Parameter: %s is not recognised" % (p))
        # delelte last ;
        msg = msg[:-1]
        return self.__sendRequest("get_scanoutput_config"
                                  , parameters=msg)

    def startScanoutput(self, handle, start=True):
        '''
        The command start_scanoutput starts the transmission of scan data for the data channel specified by the given handle.
        When started, the sensor will begin sending scan data to the client using an established UDP or TCP channel with the given
        handle - see section 3.3.1 and section 3.3.2 (of the official documentation). 
        (Re-)starting a scan data transmission also resets the counters for scan number and scan packet number in the scan data 
        header (see section 3.4.2 (of the official documentation)).  Scan data output always starts at the beginning of a
        new scan (with scan number 0 and scan packet number 1).
        @param[in] handle tcp or udp session handle
        @param[in] start flag shows if sth output should be started or stopped
        '''
        msg = "handle=" + handle
        return self.__sendRequest(str("start" if start else "stop") \
                                  + "_scanoutput"
                                  , parameters=msg)

    def stopScanoutput(self, handle):
        '''
        The command stop_scanoutput stops the transmission of scan data for the data channel specified by the given 
        handle. The scan data output stops immediately after the current scan data packet – not necessarily at the 
        end of a full scan.
        @param[in] handle tcp or udp session handle
        '''
        return self.startScanoutput(handle, start=False)

    def releaseHandle(self, handle):
        '''
        Using the command release_handle the client can release a data channel handle. Any active scan data output using this
        handle will be stopped immediately. An associated UDP-based data channel is closed by the sensor itself. An associated
        TCP-based data channel should be closed by the client.
        @param[in] handle tcp or udp session handle
        '''
        msg = "handle=" + handle
        return self.__sendRequest("release_handle"
                                  , parameters=msg)
    # ****************************END CONVINIENT METHODS****************


class Plot():
    '''
    simple plotting class (plots the data points onto a simple canvas)
    '''

    def __init__(self):
        # Set up plot
        self.figure, self.ax = plt.subplots()
        self.lines, = self.ax.plot([], [], 'o')
        # Autoscale on unknown axis and known lims on the other
        self.ax.set_autoscaley_on(True)
        self.ax.set_xlim(-3e3, 3e3)
        self.ax.set_ylim(-3e3, 3e3)
        # Other stuff
        self.ax.grid()

    def run(self, xdata, ydata):
        '''
        updates the plot with current data
        @param[in] xdata x values of the data points
        @param[in] ydata y values of the data points
        '''
        # Update data (with the new _and_ the old points)
        self.lines.set_xdata(xdata)
        self.lines.set_ydata(ydata)
        # Need both of these in order to rescale
        self.ax.relim()
        self.ax.autoscale_view()
        # We need to draw *and* flush
        self.figure.canvas.draw()
        self.figure.canvas.flush_events()


if __name__ == "__main__":

    '''
    this is an example implementation
    use at your own risk!!!
    usage: python R2000Driver.py <arg>
    arg == reboot         : reboots the sensor
    arg == 127.0.0.1:8080 : tries to connect to the dummy sensor
    arg == ""             : tries to connect to the real sensor
    '''
    sensor_ip = None
    reboot = False
    try:
        if sys.argv[1] != "reboot":
            sensor_ip = sys.argv[1]
        elif sys.argv[1] == "reboot":
            reboot = True
            sensor_ip = "192.168.99.38"
        else:
            sensor_ip = "192.168.99.38"
    except:
        # IP of the sensor when first started
        sensor_ip = "192.168.99.38"
    sensor_ip += ':'
    real = True
    if sensor_ip.split(':')[1] == "8080":
        real = False
    else:
        sensor_ip = sensor_ip[:-1]

    try:
        o = R2000Driver(sensor_ip, real=real, address="192.168.99.111")  # this is the ip address of my local_host
        if reboot:
            o.rebootDevice()
            sys.exit(0)
        else:
            o.startScanning(port=20000)

        p = Plot()

        time.sleep(.5)
        start_angle = -45
        end_angle = 45
        while True:
            time.sleep(1)
            alpha = 0
            head, dist, ampl = o.getData()
            # head,dist,ampl,alpha = o.getSegmentedData(start_angle,
            #                                          end_angle,
            #                                          [600, 3000], 100)
            # if self.run.value == 0:
            x = list()
            y = list()
            inc = alpha
            m = max(dist)
            print("new data")
            # print([str(h.num_points_scan) + " " + \
            #       str(h.packet_size) for h in head])
            for d in dist:
                x_ = -d * math.sin(inc * math.pi / 180)
                y_ = d * math.cos(inc * math.pi / 180)
                x.append(x_)
                y.append(y_)
                inc += 360. / o.samples_per_scan
            p.run(x, y)

    except:
        if sys.exc_info()[0] == SystemExit:
            sys.exit(0)
        else:
            print(sys.exc_info())
            tb.print_tb(sys.exc_info()[2])
            o.vLog(2, "Caught keyboard interrupt in" + \
                   " main... shuting down")

            if not o.process:
                o.stopScanning()
            else:
                o.stopScanning(pr=False)
            sys.exit(0)


