import cv2
import json
import numpy as np
import math

from time import time
from enum import Enum

from .functions import geo2Angle

class ObjectType(Enum):
    Unknown = 0
    Person = 1
    Bicycle = 2
    Car = 3
    Motorcycle = 4
    Bus = 5
    Truck = 6

    def __new__(cls, value):
        member = object.__new__(cls)
        member._value_ = value
        return member

    def __int__(self):
        return self.value



class BoundingBox:
    """
    Contains information aobut a single bounding box.
    Variables:
        yLeft, yRight, yTop, yBottom - coordinates of bounding box (in pixels)
        timestamp           - timestamp in seconds (float)
        x, y                - point (in pixels) that represents the bounding box. This point is in
                              the middle of the bottom line of bounding box
        birdEyeX, birdEyeY  - Coordinates corresponding to (x, y) on the Bird Eye View image.
        lon, lat            - spatial coordinates of bounding box (corrdinates of (x, y) point).
    """
    def __init__(self, xLeft, xRight, yTop, yBottom, timeStamp=None, params=None):
        """
        Arguments:
            xLeft, xRight, yTop, yBottom - bounding box coordinates
            timeStamp   - timestamp
            params      - Instance of Parameter class. If not none then function update params is executed
                          (birdEyeX, birdEyeY, lon and lat are computed).
        """

        # Bounding box coordinates
        self.xLeft = xLeft
        self.xRight = xRight
        self.yTop = yTop
        self.yBottom = yBottom

        # area in pixels
        self.area = (xRight - xLeft) * (yBottom - yTop)

        # Coordinates reduced to the point
        self.x = round((self.xLeft + self.xRight) / 2)
        self.y = self.yBottom
        self.birdEyeX = None
        self.birdEyeY = None

        # Timestamp
        self.timeStamp = timeStamp

        # Longitude and Latitude
        self.lon = None
        self.lat = None
        self.elevation = None

        self.params_updated = False
        if params is not None:
            self.updateParams(params)


    def updateParams(self, params, force_update = False):
        """
        Updates birdEye pixel coordinates and corresponding latitude and longitude.
        Arguments:
            params          - an instance of Parameters class.
            force_update    - if True, update is forced, if False (default) update is performed only if it hasn't been
                            performed before
        Returns:
            Nothing
        """

        if force_update or (not self.params_updated):
            p = np.array([[[self.x, self.y]]], dtype='float32')
            tmp = cv2.perspectiveTransform(p, params.unwarp_M)
            self.birdEyeX = tmp[0][0][0]
            self.birdEyeY = tmp[0][0][1]

            self.lon = params.lonA * self.birdEyeX + params.lonB
            self.lat = params.latA * self.birdEyeY + params.latB
            self.elevation = params.elevation

            self.params_updated = True

    def getTrackerCoordinates(self):
        """
        Returns:
            coordinates in format useful for cv2 tracker:
                (xLeft, yTop, xRight - xLeft, yBottom - yTop)
        """
        return (self.xLeft, self.yTop, self.xRight - self.xLeft, self.yBottom - self.yTop)

    def computeIoU(self, bboxes):
        """
        Coputes IoUs between this box and the list of boxes provided as an argument
        Arguments:
            boxes - list of boxes (instances of BoundingBox class)
        Returns:
            List of IoU values corresponding to the list of boxes
        """
        ioulist = []
        for box in bboxes:
            # determine the (x, y)-coordinates of the intersection rectangle
            xA = max(box.xLeft, self.xLeft)
            yA = max(box.yTop, self.yTop)
            xB = min(box.xRight, self.xRight)
            yB = min(box.yBottom, self.yBottom)

            # compute the area of intersection rectangle
            interArea = max(0, xB - xA) * max(0, yB - yA)

            # compute the intersection over union by taking the intersection
            # area and dividing it by the sum of prediction + ground-truth
            # areas - the interesection area
            iou = interArea / float(box.area + self.area - interArea)
            ioulist.append(iou)
        return ioulist

class Object():
    def __init__(self, object_type):
        assert object_type in list(ObjectType), "Make object_type not a valid ObjectType value"
        self.type = object_type
        self.bboxes = []

        self.msgCnt = 0 # BSM counter - is incremented every time when BSM is returned. The compatibility with
                        # the standards should be checked latter.

        self.tracker = None
        self.color = None # Color user for objects
        self.notDetectedCounter = 0 # Counter used for object destruction
        self.id = id(self)

        self.heading = None # Heading of the object in degrees

    def createTracker(self, img, bbox, add_box = True):
        """
        Initialized the tracker for this object. If add_box is true adds the box to list of boxes
        Arguments:
            img - image (frame) used for initialization
            bbox - bounding box (instance of BoundingBox class) used for initialization
        Returns:
            succes of initialization (results of tracker.init(img, bbox) function
        """

        assert isinstance(bbox, BoundingBox), (
            "bbox should be an instance of BoundingBox class. It is {} type.".format(type(bbox))
        )

        self.tracker = cv2.TrackerMIL_create()
        success = self.tracker.init(img, bbox.getTrackerCoordinates())
        if add_box:
            self.bboxes.append(bbox)
        return success

    def updateTracker(self, img, timeStamp=None):
        """
        Updates the tracker tor this object. If the update was successful adds new bounding box to the list.
        Arguments:
            img - image (frame) used for initialization
            timeStamp - timestamp of an image (if none, current timestamp is taken
        Returns:
            BoundingBox object of the new tracker, or False, if update was not successful.
        """
        success, bbox = self.tracker.update(img)

        if success:
            if timeStamp is None:
                timeStamp = time()
            bbox = BoundingBox(bbox[0], bbox[0] + bbox[2], bbox[1], bbox[1] + bbox[3], timeStamp)
            self.addBoundingBox(bbox)
            return bbox
        else:
            return False


    def computeIoU(self, bboxes, boxpos = -1):
        """
        Coputes IoUs between the selected (last by default) box and the list of boxes provided as an argument
        Arguments:
            boxes - list of boxes (instances of BoundingBox class)
            poxpos - index of the bounding box list from this object (default = -1 - use last box)
        Returns:
            List of IoU values corresponding to the list of boxes
        """
        return self.bboxes[boxpos].computeIoU(bboxes)

    def addBoundingBox(self, bbox):
        """
        Adds bounding box to the list of bounding boxes. Bounding box must be an instance of BoundingBox class
        """

        assert isinstance(bbox, BoundingBox), (
            "bbox should be an instance of BoundingBox class. It is {} type.".format(type(bbox))
        )

        self.bboxes.append(bbox)

    def updateBoundingBox(self, bbox, img=None):
        """
        Updates bounding box from the list of bounding boxes. Bounding box must be an instance of BoundingBox class
        Arguments:
            bbox    - new bounding box (instance od BoundingBox class)
            pos     - position from bounding box list. Default = -1 (last bounding box is updated
        Returns:
            Result of tracker.init if the initialization has been executed. Otherwise None
        """

        assert isinstance(bbox, BoundingBox), (
            "bbox should be an instance of BoundingBox class. It is {} type.".format(type(bbox))
        )
        self.bboxes[-1] = bbox
        if (img is not None) and (self.tracker is not None):
            success = self.createTracker(img, bbox, add_box=False)
        else:
            success = None

        return success

    def updateBBoxParams(self, params, bboxpos = -1, force_update = False):
        """
        Updates birdEye pixel coordinates and corresponding latitude and longitude.
        Arguments:
            params          - an instance of Parameters class.
            bboxpos         - which bounding box should be updated, default = -1 (last box)
            force_update    - if True, update is forced, if False (default) update is performed only if it hasn't been
                            performed before
        Returns:
            Updated bounding box
        """

        self.bboxes[bboxpos].updateParams(params, force_update=force_update)
        return self.bboxes[bboxpos]


    def getTrajectory(self):
        """
        Returns trajectory as a list of lists [[lon1, lat1, timestamp1], [lon2, lat2, timestamp2], .....]
        """
        return [[box.lon, box.lat, box.timeStamp] for box in self.bboxes]


    def __computeDistance(self, bbox1, bbox2):
        """
        Computes speeds between two bounding boxes. For internal use only
        NOTE 1: Right now I implemented full great circle formula, but in the final version it is a good idea to change
        it into some faster approximation.
        NOTE 2: To implement the great circle I used the code from: https://gist.github.com/nickjevershed/6480846
        """

        degrees_to_radians = math.pi / 180.0

        # phi = 90 - latitude
        phi1 = (90.0 - bbox1.lat) * degrees_to_radians
        phi2 = (90.0 - bbox2.lat) * degrees_to_radians

        # theta = longitude
        theta1 = bbox1.lon * degrees_to_radians
        theta2 = bbox2.lon * degrees_to_radians

        cos = (math.sin(phi1) * math.sin(phi2) * math.cos(theta1 - theta2) +
           math.cos(phi1) * math.cos(phi2))

        cos = max(-1, min(1, cos)) # in case of numerical problems

        ret = 6731000 * math.acos(cos) # mutliplied by earth radius in meters


        return ret

    def getSpeed(self):
        """
        Returns:
            - speed ob the objects [m/s]. Speed is computed based on the last two bounding boxes
            - distance that has been driven (in meters)
            - time (in seconds)
        """

        if len (self.bboxes) < 2:
            return None, None, None

        dist = self.__computeDistance(self.bboxes[-2], self.bboxes[-1])
        ttime = self.bboxes[-1].timeStamp - self.bboxes[-2].timeStamp

        if ttime == 0:
            return 0.0, 0.0, 0.0

        return dist / ttime, dist, ttime

    def getHeading(self):
        """
        Returns the heading in angles - 0 = N, 90 = E (probably, didn't check it :>).
        """
        if len (self.bboxes) < 2:
            return None
        angle = geo2Angle(self.bboxes[-2].lat, self.bboxes[-2].lon, self.bboxes[-1].lat, self.bboxes[-1].lon)
        return angle

    def getElevation(self):
        """
        Returns: elevation of an object (elevation of the last bounding box)
        """
        if len(self.bboxes) > 0:
            return self.bboxes[0].elevation
        else:
            return None

    def getBsm(self, retDic=True, params=None, roundValues=True, includeNone=True):
        """
        Returns the json file with Basic Safety Message
        NOTE - this is an experimental version of the function, I am not sure if BSM should be formatted like this
        and contain such information. This function will be corrected in cooperation with Kaveh. DO NOT USE AS A
        PATTERN FOR BSM MESSAGE
        Arguments:
            retDic      - if True (default) dictionary is returned. Otherwise json.dumps(dic) is returned.
            params      - object with parameters
            roundValues - if True (default) the values are rounded to reasonable numbers (6 digits for lat and lon,
                          2 digits for speed, full angles for heading, 2 digits for secMark
            includeNone - if True (default) None values are included to the message.
        """

        if len(self.bboxes) == 0:
            return None

        if params is not None:
            self.bboxes[-1].updateParams(params)
            if len(self.bboxes) > 1:
                self.bboxes[-2].updateParams(params)

        m = {}
        m['msgCnt'] = self.msgCnt
        m['id'] = self.id
        m['objectType'] = int(self.type)

        if roundValues:
            m['secMark'] = round(time(), 2)
            m['lat'] = round(self.bboxes[-1].lat, 6)
            m['lon'] = round(self.bboxes[-1].lon, 6)

            m['speed'], _, _ = self.getSpeed()
            if m['speed'] is not None:
                m['speed'] = round(m['speed'], 2)

            m['heading'] = self.getHeading()
            if m['heading'] is not None:
                m['heading'] = round(m['heading'], 0)
        else:
            m['secMark'] = time()
            m['lat'] = self.bboxes[-1].lat
            m['lon'] = self.bboxes[-1].lon
            m['speed'], _, _ = self.getSpeed()
            m['heading'] = self.getHeading()


        m['elevation'] = self.getElevation()
        m['accuracy'] = 4.0 # From the top of my head, should be corrected later
        m['transmition'] = None
        m['angle'] = None
        m['accelSet'] = None
        m['brakes'] = None
        m['size'] = None

        if not includeNone:
            m = {i: m[i] for i in m if m[i] is not None}


        self.msgCnt += 1
        if retDic:
            return m

        msg = json.dumps(m)
        return msg
