# SenseLink
A tool to inform a Sense Home Energy Monitor of **known** energy usage in your home, written in Python. A Docker image is also provided!

If you're sourcing your energy usage from ESP8266/ESP32 devices via ESPHome, check out my partner project [ESPSense](https://github.com/cbpowell/ESPSense)! You might be able to report power usage to Sense directly from your device, including other cheap commercial Smart Plugs!

# About
SenseLink is a tool that emulates the energy monitoring functionality of [TP-Link Kasa HS110](https://www.tp-link.com/us/home-networking/smart-plug/hs110/) Smart Plugs, and allows you to report "custom" power usage to your [Sense Home Energy Monitor](https://sense.com) based on other parameters.

SenseLink can emulate multiple plugs at the same time, and can report:
1. Static/unchanging power usage
2. Dynamic power usage based on other parameters through API integrations (e.g. a dimmer brightness value)
3. Aggregate usage of any number of other plugs (static or dynamic)

At the moment, dynamic power plugs can source data from the [Home Assistant](https://www.home-assistant.io) (Websockets API) and MQTT. Plus, other integrations should be relatively easy to implement!

Aggregate "plugs" sum the power usage data from the specified sub-elements, and report usage just as dynamically.

While Sense [doesn't currently](https://community.sense.com/t/smart-plugs-frequently-asked-questions/7211) use the data from smart plugs for device detection algorithm training, you should be a good citizen and try only provide accurate data! Not to mention, incorrectly reporting your own data hurts your own monitoring as well!

**You should use this tool at your own risk!** Sense is not obligated to provide any support related to issues with this tool, and there's no guarantee everything will reliably work, or even work. Neither I or Sense can guarantee it won't affect your Sense data, particularly if things go wrong!


# Configuration
Configuration is defined through a YAML file, that should be passed in when creating an instance of the `SenseLink` class. See the [`config_example.yml`](https://github.com/cbpowell/SenseLink/blob/master/config_example.yml) file for examples of how to write configurations (note the example config itself is not a valid demo config!).

The YAML configuration file should start with a top level `sources` key, which defines an array of sources for power data. Each source then has a `plugs` key to define an array of individual emulated plugs, plugs other configuration details as needed for that particular source. The current supported sources types are:
- `static`: Plugs with unchanging power values
- `hass`: Home Assistant, via the Websockets API
- `mqtt`: MQTT, via a MQTT broker
- `aggregate`: Summed values of other plugs, for example for a whole room - useful for staying under the Sense limit of ~20 plugs!
- `mutable`: Plugs designed to have their power values changed by other areas of the code/program. Primarily only useful when using SenseLink as a module in other code. See the [`module_usage_example.py`](https://github.com/cbpowell/SenseLink/blob/master/module_usage_example.py) file.

See the [`config_example.yml`](https://github.com/cbpowell/SenseLink/blob/master/config_example.yml) for examples of each, and [the wiki](https://github.com/cbpowell/SenseLink/wiki) for configuration details!

## Plug Definition
### Required Parameters
Each plug definition needs, at the minimum, the following parameters:
- `alias`: The plug name - this is the name you'd see if this was a real plug configured in the TP-Link Kasa app
- `mac`: A **unique** MAC address for the emulated plug. This is how Sense differentiates plugs!

If a `mac` value is not supplied, SenseLink will generate one at runtime - but this is almost certainly **not what you want**. With a random MAC address, a Sense will detect the SenseLink instances as "new" plug each time SenseLink is started!

You can use the `PlugInstance` module to generate a random MAC address if you don't want to just make one up. When in the project folder, use: `python3 -m PlugInstance` 

### Optional Parameters
#### Skip Rate
A `skip_rate` key and value can be provided in the plug definition. This per-plug value defines how many incoming requests will be skipped before SenseLink will allow the plug to respond. A `skip_rate` of `0` is the inherent default, and means the plug will respond to every request. A `skip_rate` of `3` will cause three (3) requests to be skipped before a response is provided.

While this is completely unverified, anecdotally it has been stated that the Sense plug limit is related to the available processing power to parse incoming replies. This feature *may* allow you to expand beyond this limit, by reducing the response rate for plugs with static or near-static power readings, and thereby reducing the response load on your Sense meter.

Note that (obviously) the value reported by Sense will not change when responses are skipped, even if your data source value is updated. In my testing, a `skip_rate` of more than `5` or `6` will cause Sense to start reporting the plug as "N/A", and values higher than that will result in the plug appearing as "Off".

#### Device ID
Each real TP-Link plug also supplies a unique `device_id` value, however based on my testing Sense doesn't care about this value. If not provided in your configuration, SenseLink will generate a random one at runtime for each plug. Sense could change this in the future, so it is probably a good idea to generate and define a static `device_id` value in your configuration. The `PlugInstances` module will provide one if run as described above.

### Minimum Configuration
A minimum configuration file and static-type plug definition will look like the following:
```yaml
sources:
- static:
    plugs:
    - BasicPlug:
        mac: 50:c7:bf:f6:4b:07
        max_watts: 15
        alias: "Basic Plug"
```

## Dynamic Plug Definition
More "advanced" plugs using smarthome/IoT integrations will require more details - see [the wiki configuration pages](https://github.com/cbpowell/SenseLink/wiki) for more information!

1. [Static plugs](https://github.com/cbpowell/SenseLink/wiki/Static-Plugs)
2. [Home Assistant plugs](https://github.com/cbpowell/SenseLink/wiki/Home-Assistant-Plugs)
3. [MQTT plugs](https://github.com/cbpowell/SenseLink/wiki/MQTT-Plugs)
4. [Mutable plugs](https://github.com/cbpowell/SenseLink/wiki/Mutable-Plugs) (Mutable plugs are dynamic only in that they may be updated directly via Python code in module usage)

## Aggregate Plug Definition
Aggregate plugs can be used to __sum the power usage__ of any number of other defined plugs (inside SenseLink). For example: if you have Caseta dimmers on multiple light switches in your Kitchen, you can define individual HASS plugs for each switch, and then specify a "Kitchen" aggregate plug comprised of all those individual HASS plugs. The Aggregate plug will report the sum power of the individual plugs, and the individual plugs will __not__ be reported to Sense independently.

Each Aggregate plug requires the following definition (similar to the Basic plug, but without the `max_watts` key):
```yaml
sources:
... # other plugs defined here!
- aggregate:
    plugs:
    - Kitchen_Aggregate:
        mac: 50:c7:bf:f6:4d:01
        alias: "Kitchen Lights"
        elements:
          - Kitchen_Overhead
          - Kitchen_LEDs
          - Kitchen_Spot
```
Note: SenseLink will prevent you from listing the same plug in more than one Aggregate plug, to prevent double-reporting.

## Additional Configuration
### Target Setting
SenseLink will respond with power usage data to the/any IP that sends the appropriate broadcast UDP request (normally your Sense monitor), unless the top-level `target` key is specified. If the `target` key is specified, SenseLink will respond to *only* that host/IP address when it receives a broadcast request. This is useful when using SenseLink on a non-Linux Docker host that does not allow using host networking (i.e. `--net=host`). You can specify the (preferably static) IP address of your Sense monitor as the target.

The `target` key should be used as follows:
```yaml
target: 192.168.1.20 # replace with your Monitor IP
sources:
- static:
    plugs:
    ...
```

# Usage
First of all, note that whatever **computer or device running SenseLink needs to be on the same subnet as your Sense Home Energy Meter**! Otherwise SenseLink won't get the UDP broadcasts from the Sense requesting plug updates. There might be ways around this with UDP reflectors, but that's beyond the scope of this document.

## Command Line / Python Interpreter
SenseLink can be installed via `pip`, using: `pip install senselink`. Alternatively you can clone the git repository and use it directly.

Once installed, SenseLinnk can be started directly via the command line using:
`python3 -m senselink -c "/path/to/your/config.yml"`

The `-l` option can also be used to set the logging level (`-l "DEBUG"`). SenseLink needs to be able to listen on UDP port `9999`, so be sure you allow incoming on any firewalls.

## Docker
A Docker image is [available](https://hub.docker.com/repository/docker/theta142/senselink) from Dockerhub, as: `theta142/SenseLink`. When running in Docker the configuration file needs to be passed in to SenseLink, and and the container needs to be able to listen on UDP port `9999`. Unfortunately the Docker network translation doesn't play nice with the Sense UDP broadcast, so you must use either:
1. Host networking (`--net=host`) on a Linux host, or
2. The [`target` configuration setting](#target-setting), with your Sense monitor IP specified. A Docker port mapping (`-p 9999:9999`) should also be set in this case.

An example run command is:

`docker run -v $(pwd)/your_config.yml:/etc/senselink/config.yml -e LOGLEVEL=INFO --net=host theta142/senselink:latest`

An example `docker-compose` file is also provided in the repository.

## In other projects
See the usage in the [`module_usage_example.py`](https://github.com/cbpowell/SenseLink/blob/master/module_usage_example.py) file.

# Todo
- Add additional integrations!
- Add a HTTP GET/POST semi-static data source type
- Make things more Pythonic (this is my first major tool written in Python!)
- Allow non-linear attribute-to-power relationships


# About
Copyright 2020, Charles Powell
