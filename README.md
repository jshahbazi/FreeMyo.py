# FreeMyo.py
BLE Bleak-based Async Python interface to the Myo Armband that doesn't require a dongle or the MyoConnect software.  This has been primarily designed for macOS and its UUID-based BLE connections.

Based on specs from Thalmic Labs: https://github.com/thalmiclabs/myo-bluetooth and work done by PerlinWarp on pyomyo here: https://github.com/PerlinWarp/pyomyo and also Open-Myo: https://github.com/Alvipe/Open-Myo

Initially this is CLI-based, but I'll be adding a GUI to it soon.

---

Note: Requires Python 3.10 due to the use of the *match* expression

---

### Built with:
[Bleak](https://github.com/hbldh/bleak)