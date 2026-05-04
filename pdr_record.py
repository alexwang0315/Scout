# ------------------------------------------------------------
# PDRRecord – 對應 iPhone / Apple Watch 上傳的完整 JSON
# ------------------------------------------------------------
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field

class PDRRecord(BaseModel):
    # ------------------- 基本識別 -------------------
    deviceID: Optional[str] = None
    loggingTime: Optional[str] = None
    deviceOrientation: Optional[str] = None
    deviceOrientationTimeStamp_since1970: Optional[str] = None

    # ------------------- Accelerometer (G) -------------------
    accelerometerAccelerationX: Optional[float] = Field(None, alias="accelerometerAccelerationX")
    accelerometerAccelerationY: Optional[float] = Field(None, alias="accelerometerAccelerationY")
    accelerometerAccelerationZ: Optional[float] = Field(None, alias="accelerometerAccelerationZ")

    # ------------------- Gyroscope (rad/s) -------------------
    gyroRotationX: Optional[float] = Field(None, alias="gyroRotationX")
    gyroRotationY: Optional[float] = Field(None, alias="gyroRotationY")
    gyroRotationZ: Optional[float] = Field(None, alias="gyroRotationZ")

    # ------------------- Magnetometer (µT) -------------------
    magnetometerX: Optional[float] = Field(None, alias="magnetometerX")
    magnetometerY: Optional[float] = Field(None, alias="magnetometerY")
    magnetometerZ: Optional[float] = Field(None, alias="magnetometerZ")

    # ------------------- Motion orientation (rad) -------------------
    motionYaw:   Optional[float] = Field(None, alias="motionYaw")
    motionPitch: Optional[float] = Field(None, alias="motionPitch")
    motionRoll:  Optional[float] = Field(None, alias="motionRoll")

    # ------------------- Altimeter -------------------
    altimeterPressure:          Optional[float] = Field(None, alias="altimeterPressure")
    altimeterRelativeAltitude:  Optional[float] = Field(None, alias="altimeterRelativeAltitude")
    altimeterReset:             Optional[float] = Field(None, alias="altimeterReset")
    altimeterTimestamp_sinceReboot: Optional[float] = Field(None, alias="altimeterTimestamp_sinceReboot")

    # ------------------- GPS / Location -------------------
    locationLatitude:  Optional[float] = Field(None, alias="locationLatitude")
    locationLongitude: Optional[float] = Field(None, alias="locationLongitude")
    locationAltitude:  Optional[float] = Field(None, alias="locationAltitude")
    locationCourse:   Optional[float] = Field(None, alias="locationCourse")
    locationSpeed:    Optional[float] = Field(None, alias="locationSpeed")
    locationHorizontalAccuracy: Optional[float] = Field(None, alias="locationHorizontalAccuracy")
    locationMagneticHeading:    Optional[float] = Field(None, alias="locationMagneticHeading")
    locationTrueHeading:        Optional[float] = Field(None, alias="locationTrueHeading")

    # ------------------- Pedometer / Activity -------------------
    pedometerNumberOfSteps: Optional[int]   = Field(None, alias="pedometerNumberOfSteps")
    pedometerDistance:      Optional[float] = Field(None, alias="pedometerDistance")
    pedometerCurrentPace:   Optional[float] = Field(None, alias="pedometerCurrentPace")
    activity:               Optional[str]   = Field(None, alias="activity")
    activityActivityConfidence: Optional[int] = Field(None, alias="activityActivityConfidence")
    activityActivityStartDate:   Optional[str] = Field(None, alias="activityActivityStartDate")

    # ------------------- Battery / Audio / IP (optional) -------------------
    batteryLevel:  Optional[float] = Field(None, alias="batteryLevel")
    batteryState:  Optional[int]   = Field(None, alias="batteryState")
    avAudioRecorderAveragePower: Optional[float] = Field(None, alias="avAudioRecorderAveragePower")
    avAudioRecorderPeakPower:    Optional[float] = Field(None, alias="avAudioRecorderPeakPower")
    IP_en0:  Optional[str] = Field(None, alias="IP_en0")
    IP_pdp_ip0: Optional[str] = Field(None, alias="IP_pdp_ip0")

    # ------------------- 原始時間戳 (自 Reboot) -------------------
    accelerometerTimestamp_sinceReboot: Optional[float] = Field(None, alias="accelerometerTimestamp_sinceReboot")
    gyroTimestamp_sinceReboot:           Optional[float] = Field(None, alias="gyroTimestamp_sinceReboot")
    magnetometerTimestamp_sinceReboot:   Optional[float] = Field(None, alias="magnetometerTimestamp_sinceReboot")
    motionTimestamp_sinceReboot:         Optional[float] = Field(None, alias="motionTimestamp_sinceReboot")

    class Config:
        allow_population_by_field_name = True
        extra = "ignore"
