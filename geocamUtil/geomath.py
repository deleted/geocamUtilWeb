
import math
from math import pi, sqrt, sin, tan, cos, atan2

EARTH_RADIUS_METERS = 6371010
DEG2RAD = pi / 180.0
RAD2DEG = 180.0 / pi

WGS84_A = 6378137.0
WGS84_F = 1.0/298.257223563
WGS84_E2 = 2*WGS84_F - WGS84_F**2

def calculateDiffMeters(a, b):
    """
    a and b are WGS84 lat/lon coordinates.  returns [x,y] displacement
    in meters that would get you from b to a.  x is easting and y is
    northing.
    """

    # this is a crude approximation but works fine locally, probably
    # within 1% for distances under 10 km and latitude within +/- 75
    # degrees.
    latDiff = (a[1] - b[1]) * DEG2RAD
    lonDiff = (a[0] - b[0]) * DEG2RAD
    lat = 0.5 * (a[1] + b[1]) * DEG2RAD
    return [math.cos(lat) * EARTH_RADIUS_METERS * lonDiff,
            EARTH_RADIUS_METERS * latDiff]

def addMeters(latLon, xy):
    """
    approximate inverse of calculateDiffMeters

    diff = calculateDiffMeters(a, b) <-> a = addMeters(b, diff)
    """

    x = xy[0]
    y = xy[1]
    latRad = latLon[1] * DEG2RAD
    latDiff = y / EARTH_RADIUS_METERS
    lonDiff = x / (math.cos(latRad) * EARTH_RADIUS_METERS)
    return [latLon[0] + RAD2DEG * lonDiff,
            latLon[1] + RAD2DEG * latDiff]

def xyFromPolar(rangeMeters, bearingDegrees):
    thetaRadians = DEG2RAD * (90.0 - bearingDegrees)
    x = rangeMeters * math.cos(thetaRadians)
    y = rangeMeters * math.sin(thetaRadians)
    return [x, y]

def getLength(v):
    x = v[0]
    y = v[1]
    return math.sqrt(x*x + y*y)

def getBearingDegrees(v):
    x = v[0]
    y = v[1]
    result = 90.0 - RAD2DEG * math.atan2(y, x)
    if result < 0:
        result += 360
    return result

class UtmProjector:
      def __init__(self, zone, northernHemisphere):
            self._zone = zone
            self._northernHemisphere = northernHemisphere

      @staticmethod
      def lonToUtmZone(lon):
            zone = int((lon+180)/6) + 1
            return zone

      @staticmethod
      def latToUtmZoneLetter(lat):
            index = int((lat+80)/8)
            if (index < 0) or (index>20):
                  print 'zone letter undefined for %f' % lat
                  return None
            print 'zoneLetter: index = %d' % index
            letters = ['C','D','E','F','G','H','J','K','L','M','N',
                       'P','Q','R','S','T','U','V','W','X','X']
            letter = letters[index]
            return letter

      # Equations from USGS Bulletin 1532 
      # Written by Chuck Gantz- chuck.gantz@globalstar.com
      def utmFromLatLon(self, lonDeg, latDeg):
            a = WGS84_A
            e2 = WGS84_E2
            k0 = 0.9996
  
            # Make sure the longitude is between -180.00 .. 179.9
            if lonDeg < -180:
                  lonDeg += 360
            elif lonDeg >= 180:
                  lonDeg -= 360
  
            latRad = latDeg*DEG2RAD
            lonRad = lonDeg*DEG2RAD
  
            lonOrigin = (self._zone - 1)*6 - 180 + 3;  #+3 puts origin in middle of zone
            lonOriginRad = lonOrigin * DEG2RAD
  
            eccPrimeSquared = (e2)/(1-e2)
  
            N = a/sqrt(1-e2*sin(latRad)*sin(latRad))
            T = tan(latRad)*tan(latRad)
            C = eccPrimeSquared*cos(latRad)*cos(latRad)
            A = cos(latRad)*(lonRad-lonOriginRad)
  
            M = (a*((1 - e2/4 - 3*e2*e2/64 - 5*e2*e2*e2/256)*latRad
                    - (3*e2/8 + 3*e2*e2/32 + 45*e2*e2*e2/1024)*sin(2*latRad)
                    + (15*e2*e2/256 + 45*e2*e2*e2/1024)*sin(4*latRad)
                    - (35*e2*e2*e2/3072)*sin(6*latRad)))
  
            east = (k0*N*(A+(1-T+C)*A*A*A/6
                          + (5-18*T+T*T+72*C-58*eccPrimeSquared)*A*A*A*A*A/120)
                    + 500000.0)
            north = (k0*(M+N*tan(latRad)
                         *(A*A/2+(5-T+9*C+4*C*C)*A*A*A*A/24
                           + (61-58*T+T*T+600*C-330*eccPrimeSquared)*A*A*A*A*A*A
/720)))
            if 0: # southern hemisphere
                  north += 1e+7 #10,000,000 meter offset for southern hemisphere
            return (east, north)

      # Equations from USGS Bulletin 1532 
      # Written by Chuck Gantz- chuck.gantz@globalstar.com
      def latLonFromUtm(self, east, north):
            k0 = 0.9996
            a = WGS84_A
            e2 = WGS84_E2
            e1 = (1-sqrt(1-e2))/(1+sqrt(1-e2))
            
            x = east - 500000.0 # remove 500,000 meter offset for longitude
            if self._northernHemisphere:
                  hemiNumber = 0
            else:
                  hemiNumber = 1
            y = north - hemiNumber * 1e+7
  
            lonOrigin = (self._zone - 1)*6 - 180 + 3  #+3 puts origin in middle of zone
            
            eccPrimeSquared = (e2)/(1-e2)
  
            M = y / k0
            mu = M/(a*(1-e2/4-3*e2*e2/64-5*e2*e2*e2/256))
            
            phi1Rad = (mu + (3*e1/2-27*e1*e1*e1/32)*sin(2*mu)
                       + (21*e1*e1/16-55*e1*e1*e1*e1/32)*sin(4*mu)
                       + (151*e1*e1*e1/96)*sin(6*mu))
            phi1 = phi1Rad * RAD2DEG
            
            N1 = a/sqrt(1-e2*sin(phi1Rad)*sin(phi1Rad))
            T1 = tan(phi1Rad)*tan(phi1Rad)
            C1 = eccPrimeSquared*cos(phi1Rad)*cos(phi1Rad)
            R1 = a*(1-e2)/pow(1-e2*sin(phi1Rad)*sin(phi1Rad), 1.5)
            D = x/(N1*k0)
            
            lat = (phi1Rad - (N1*tan(phi1Rad)/R1)
                   *(D*D/2-(5+3*T1+10*C1-4*C1*C1-9*eccPrimeSquared)*D*D*D*D/24
                     +(61+90*T1+298*C1+45*T1*T1-252*eccPrimeSquared-3*C1*C1)*D*D*D*D*D*D/720))
            dlon = ((D-(1+2*T1+C1)*D*D*D/6+(5-2*C1+28*T1-3*C1*C1+8*eccPrimeSquared+24*T1*T1)
                     *D*D*D*D*D/120)/cos(phi1Rad))
            return (lonOrigin + RAD2DEG * dlon,
                    RAD2DEG * lat)
