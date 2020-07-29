# SenseLink
A tool to inform a Sense Home Energy Monitor of **known** energy usage in your home, written in Python. A Docker image is also provided!

## About
SenseLink is a tool that emulates the energy monitoring functionality of [TP-Link Kasa HS110](https://www.tp-link.com/us/home-networking/smart-plug/hs110/) Smart Plugs, and allows customization of the reported power usage. The [Sense Home Energy Monitor](https://sense.com) features an integration with the TP-Link Kasa energy monitoring products, and SenseLink uses that integration to allow you to report device energy usage without actually owning/using a Kasa device.

SenseLink can emulate multiple plugs at the same time, and can report:
- Static/unchanging power usage
- Dynamic power usage based on other parameters through API integrations (e.g. a dimmer brightness value)

At the moment the only API integration is with a [Home Assitant](https://www.home-assistant.io) Websockets API, but other integrations should be relatively easy to implement!

## Usage and Configuration
Configuration is handled through a YAML file, that should be passed in when creating an instance of the `SenseLink` class. See the `example_usage.py` and `config_example.yml` files for a basic setup.

### Configuration
The YAML configuration file should start with a top level `sources` key, which defines an array of sources for power data. Each source then has a `plugs` key to define an array of individual emulated plugs, plugs other configuration details as needed for that particular source. The current supported sources types are:
- `hass`: Home Assistant, via Websockets API
- `static`: Plugs with unchanging power values

See the [`config_example.yml`](https://github.com/cbpowell/SenseLink/blob/master/config_example.yml) for a full example

#### Required Plug Details - All Source Types
Each plug definition needs, at the minimum, the following parameters:
- `alias`: The plug name - this is the name you'd see if this was a real plug configured in the TP-Link Kasa app
- `max_watts`: The maximum wattage to report, or in the case of a `static` plug the (unchanging) wattage to report
- `mac`: A **unique** MAC address for the emulated plug. This is how Sense differentiates plugs

If a `mac` value is not supplied, SenseLink will generate one at runtime - but this is **not** what you want. With a random MAC address, a Sense will detect the SenseLink instances as "new" plug each time the program is run!

You can use the `PlugInstance` module to generate a random MAC address (with the TP-Link vendor code) if you don't want to just make one up. When in the project folder, use: `python3 -m PlugInstance` 

#### Static Source Plugs
No additional configuration is necessary beyond the basic required configuration above.

#### Home Assistant (HASS) Source and Plugs
To provide dynamic power values to Sense based on a value from a HASS entity, SenseLink needs to be configured with:
1. Details to communicate with the HASS Websockets API, and
2. The entity and attribute to utilize for power calculation for each HASS-source plug

##### 1. HASS API configuration
For a HASS source, you need to provide the `url` for your HASS server [Websockets API](https://developers.home-assistant.io/docs/api/websocket/), and a ["Long lived access token"](https://www.home-assistant.io/docs/authentication/#your-account-profile) as the `auth_token`. These values need to be defined as key-values in the configuration YAML at the same level as the `plugs` array, as seen in the example configuration:
````yaml
sources:
  - hass:
      url: "ws://your.HASS.API.URL.here"
      auth_token: "your_token_here"
      plugs:
      - FirstPlugHere: ...
````
##### 2. HASS Source Plug Configuration
For each plug utilizing a HASS entity attribute, the following configuration needs to be supplied in addition to the basic requirements from above. Some keys can be ommitted, and the noted default value will be used.

- `entity_id` [Required]: This tells SenseLink what HASS entity to observe for data.
- `attribute` [Required]: This tells SenseLink what attribute of the specified entity to observe to calculate power usage. For example, `brightness` for a dimmer switch.
- `attribute_max` [Required]: The maximum value of the attribute, corresponding the _highest_ power consumption of the entity.
- `max_watts` [Required]: The wattage to report to Sense when the specified attribute is at the maximum value, as defined by `attribute_max`
- `attribute_min`: The minimum value of the attribute, corresponding to the _lowest_ power consumption of the entity (Defaults to `0.0`)
- `min_watts`: The wattage to report to Sense when the specified attribute is at the minimum value, as defined by `attribute_min`
- `off_usage`: The wattage to supply when the entity is described as "off" by HASS. This allows you to potentially specify the difference between an idle power and and off power (Defaults to value supplied for `min_watts`, or `0.0` if none)
- `off_state_key`: The text value to utilize to determine if the HASS API is reporting the [entity state](https://developers.home-assistant.io/docs/api/websocket#subscribe-to-events) as "off" (Defaults to "off")

SenseLink monitors HASS update events, and scales the reported wattage linearly based on the provided values. For example, if a HASS-connected dimmer switch provides values between `0.0` (off) and `255` (full on) for an attribute called `brightness`, and is connected to four 60 watt incandecent bulbs, you would provide the following plug configuration:
````yaml
- KitchenLights:
    alias: "Kitchen Lights"
    entity_id: light.kitchen_main_lights
    mac: 50:c7:bf:f6:4b:08
    attribute: brightness
    min_watts: 0
    max_watts: 240
    attribute_min: 0
    attribute_max: 255
````
At `0.0` brightness (off), SenseLink would report 0 watts. At `153.0` (60%) brightness, SenseLink will report 144 watts.

If you don't know exact consumption values, the best way to determine a device power usage is to monitor the power usage manually on the Sense power graph while adjusting the entity attribute of interest, and capture min/max values.

### Usage
#### Command Line
SenseLink can be started directly via the command line:
`python3 ./SenseLink.py -c "/path/to/your/config.yml`

The `-l` option can also be used to set the logging level (`-l "DEBUG"`). SenseLink needs to be able to listen on UDP port `9999`, so be sure you allow incoming on any firewalls.

#### Docker
A Docker image is available from Dockerhub, as: `theta142/SenseLink`. When running in Docker SenseLink needs to be passed the configuration file, and needs to be able to listen on UDP port `9999`. Unfortunately Docker doesn't currently seem to play nice with UDP broadcasts, so `--net=host` is required and therefore the specific port exposure is unnecessary. An example run command is:

`docker run -v $(pwd)/config_private.yml:/etc/senselink/config.yml -e LOGLEVEL=INFO --net=host theta142/senselink:latest`

An example `docker-compose` file is also provided in the repository.

#### In other projects
See the usage in the [`usage_example.py`](https://github.com/cbpowell/SenseLink/blob/master/usage_example.py) file.

## Todo
- Add additional integrations!
- Add a HTTP GET/POST semi-static data source type
- Make things more Pythonic (this is my first major tool written in Python!)
