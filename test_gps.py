from node1_crash_unit.sensors.gps import GPSSensor
import time

gps = GPSSensor()

while True:
    pos = gps.get_position()
    print(pos)
    time.sleep(1)
