# Your first S7 PLC connection: read, trend and write

A practical companion to the S7 video tutorial. Start with the supplied layout, connect a local PLC simulator, read REAL/INT values, plot live pressure, and write a BOOL enable bit and INT speed.

**Aligned on 2026-11-16:** FluentHMI Studio **0.7.0**, PyQt UI Designer **0.7.0**, FluentPLC Simulator **0.1.1**, UIDP **1.1**. Local validation is on macOS arm64 with a real loopback S7 connection; this is not physical Siemens PLC validation.

[Video and illustrated tutorial](https://hmi.modusignal.cn/tutorials/12-s7-plc/?lang=en)

## Files and expected result

- [English HMI project](../../examples/tutorials/13-S7-PLC-Monitor-en.uidp)
- [Chinese HMI project](../../examples/tutorials/13-S7PLC联调.uidp)
- [Simulator project](../../examples/tutorials/13-s7-first-plc.plcsim.json)

The two HMI projects have the same IDs, addresses and commands; only visible text differs. Use the language variant that matches the screenshots. Both desktop HMI editions open the same project. The browser editor does not implement this S7 backend.

| Point | Address / type | Behavior |
| --- | --- | --- |
| Pump enable | `DB1.DBX0.0 / BOOL` | Manual; starts off; switch reads and writes it |
| Neighbor bit | `DB1.DBX0.7 / BOOL` | Starts on; stays on when the enable bit changes |
| Speed feedback | `DB1.DBW2 / INT` | Starts at 900 rpm; input and preset button write here |
| Temperature | `DB1.DBD4 / REAL` | Fixed at 23.5 °C; numeric display and gauge |
| Pressure | `DB1.DBD8 / REAL` | Sine rule, 0.8–1.6 bar over an 8 s period; display and trend |


Local evidence: the C++ 0.7.0 Studio Preview and exported Runtime performed real simulator reads and writes on port 1102. Py 0.7.0 native PreviewCanvas was separately verified with the same project on a temporary port 21112 instance: REAL 23.5, five trend samples, INT 900 → 1500 → 900, and BOOL byte 128 → 129 → 128 with the neighbor bit preserved. Four GUI writes were verified independently. The official screenshots and video record the C++ UI; this lesson did not build or record a Py exported application.

## 1. Start the simulator

Download [FluentPLC Simulator 0.1.1](https://github.com/txp666/FluentPLC-Simulator/releases/tag/v0.1.1). Open the supplied `.plcsim.json` project in the simulator while its server is stopped. Confirm `127.0.0.1`, port `1102`, then start the server. Loading/applying the project restores its initial values.

The CLI executable shipped with the simulator can run the same project:

```sh
FluentPLCServer --project 13-s7-first-plc.plcsim.json --listen 127.0.0.1 --port 1102
```

On Windows use `FluentPLCServer.exe`; on macOS it is inside the simulator app's `Contents/MacOS/` directory. Port 1102 is the example's non-privileged local port; a real PLC commonly uses 102. If you change the port, change it on the HMI card as well.

The simulator provides S7 communication and changing values. It does not execute ladder logic, STEP 7 or TIA Portal programs.

## 2. Open and connect the HMI

Use [FluentHMI Studio 0.7.0](https://github.com/txp666/FluentHMI-Studio/releases/tag/v0.7.0) or [PyQt UI Designer 0.7.0](https://github.com/txp666/PyQt-UI-Designer/releases/tag/v0.7.0). Packaged applications include the native S7 library.

Open the `.uidp` project. Its card ID is `lesson-plc`; the visible title can be renamed without changing the source ID. Check the connection properties:

| Setting | Value |
| --- | --- |
| Host | `127.0.0.1` |
| Port | `1102` |
| Rack / slot | `0 / 1` |
| Connection type | `PG (1)` |
| Default poll period | `200 ms` |
| Timeout | `1000 ms` |
| Auto-connect | Off |

Run Preview, then click **Connect** on the S7 card. Temperature should read **23.5 °C**, speed **900 rpm**, and pressure should vary between **0.8 and 1.6 bar**. The project starts disconnected so opening it alone does not connect.

![The connected tutorial project in a C++ 0.7.0 exported application, light theme](https://hmi.modusignal.cn/tutorials/assets/12-s7-plc/v070/en/preview-light.webp)

*Actual C++ 0.7.0 exported application connected to the local simulator. Preview uses the same S7 runtime.*

## 3. Read by address and type

Select the temperature display and inspect its data binding: mode **S7**, source **lesson-plc**, address **DB1.DBD4**, type **REAL**. The same point also drives the gauge.

```json
{"parseMode":"S7","sourceCardId":"lesson-plc",
 "s7":{"address":"DB1.DBD4","dataType":"REAL","period":0}}
```

`DB1` is the data block; `DBD4` starts at byte 4 and occupies four bytes. Speed uses `DB1.DBW2 / INT`, two bytes starting at byte 2. A BOOL uses a bit address such as `DB1.DBX0.0`. Address width and type must match. A point period of `0` follows the connection default; a positive period gives that point its own millisecond interval.

## 4. Plot the pressure

The trend's first curve uses **S7**, source **lesson-plc**, and **DB1.DBD8 / REAL**. It reads the simulator's sine value through the same S7 connection; the chart is not generating the pressure data itself.

```json
{"_curve_0_parseMode":"S7","_curve_0_sourceCardId":"lesson-plc",
 "_curve_0_s7":{"address":"DB1.DBD8","dataType":"REAL","period":0}}
```

## 5. Write enable and speed

A control's receive binding and send settings are separate. The switch is bound to `DB1.DBX0.0 / BOOL` for feedback, and its S7 command targets the same bit on `lesson-plc`. ON sends `1`, OFF sends `0`.

```json
{"commandMode":"S7","commandTargetId":"lesson-plc",
 "s7Command":{"address":"DB1.DBX0.0","dataType":"BOOL",
              "value":"1","onValue":"1","offValue":"0"}}
```

Toggle it on and off. The readback follows; the adjacent bit `DB1.DBX0.7` remains on. Native BOOL writes change one bit rather than replacing the entire byte.

Enter **1500** in the speed field and press **Enter**. Its send mode is S7 and target point is `DB1.DBW2 / INT`. The display above should read **1500 rpm** from the PLC. Click **Preset 900 rpm** to write the fixed value `900`; pressure keeps changing independently.

## 6. Save and export

Save the project. The C++ edition exports an independent runtime application without requiring a compiler. The Python edition exports editable source or builds an application using its packaging flow; S7 exports include the native library and notices. Build/export for the target operating system and architecture.

S7 projects use UIDP **1.1** and need an S7-capable desktop version; older designers reject them. Projects without S7 remain at UIDP 1.0.

## Troubleshooting and scope

| Symptom | Check |
| --- | --- |
| Connection fails | Simulator running; host and port match; card rack/slot values |
| Connected but wrong values | Source card, DB number, byte/bit offset and data type |
| Value changes back after a write | A generated simulator rule is driving that point; writable controls should target manual tags |
| UI changes but PLC does not | Inspect send mode and explicit target card, not only the receive binding |

This implements classic absolute-address S7comm. S7-300/400 are the primary targets. Compatible S7-1200/1500 configurations must permit PUT/GET and use non-optimized global DB access. S7CommPlus, optimized DBs and symbolic access are not included. Read the [S7 setup and limits](../s7.md) before using a physical PLC.

Configuration references: [Snap7 client / S7-1200 and S7-1500 notes](https://snap7.sourceforge.net/snap7_client.html) and [Siemens PUT instruction documentation](https://docs.tia.siemens.cloud/r/en-us/v20/s7-communication-s7-1200-s7-1500/put-write-data-to-a-remote-cpu-s7-1200-s7-1500). Check the manual for the actual CPU and firmware.
