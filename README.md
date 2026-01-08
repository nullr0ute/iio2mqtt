# iio2mqtt
A small service to take IIO sensor readings and publish to MQTT

The Linux Industral I/O subsystem (IIO) provides a standard for devices
to either provide input, such as enviromental (temp, humidty, pressure),
colour, light, gyroscopes, inertial measurement units (IMUs) and other
similar things.

The iio2mqtt service is designed to read these sensors and provide the
data onto a MQTT message bus. It's designed to be simple and relatively
straight forward way to do this using the Linux IIO interface rather
than needing a raft of python libraries for each different sensor.
