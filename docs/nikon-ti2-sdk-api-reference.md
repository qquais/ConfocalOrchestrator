# Nikon Ti2 Ax SDK API Reference

> **Reference document**, not a narrative one — see [microscope-notes.md](microscope-notes.md)
> for the story of how the SDK connection was confirmed, unit calibration,
> and open investigations. This file is a structured map of what's
> actually *in* the generated bindings: interfaces, properties, methods,
> constants - so you don't have to read all 2200+ lines of
> `.venv/Lib/site-packages/NkTi2Ax.py` to find something.

## What this file is

`NkTi2Ax.py` is **generated code**, not something anyone in this repo
wrote by hand: it's the output of pywin32's `makepy`, run against the
Nikon Ti2 Ax SDK's installed COM type library (`NkTi2Ax.dll`). Its header
records exactly how it was produced:

```
# Created by makepy.py version 0.5.01
# From type library 'NkTi2Ax.dll'
# On Sun Aug  2 00:47:12 2026
```

It lives at `.venv/Lib/site-packages/NkTi2Ax.py`, is **gitignored** (like
the rest of `.venv/`), and regenerates automatically the first time
`import NkTi2Ax` runs against a machine with the SDK installed (via
`win32com.client.gencache`) - so it won't be identical byte-for-byte
across machines/SDK versions, only interface-compatible. Every property
name, method signature, and dispid below reflects the SDK version
installed on **this** machine as of 2026-08-17; re-check this file if the
SDK is ever upgraded.

This project talks to it through exactly one hand-written wrapper:
[`acquisition/backends/nis_sdk.py`](../acquisition/backends/nis_sdk.py)
(`NISSdk` class) - everything below is background for extending that
file, not a replacement for reading it.

## Connecting: CoClasses

A CoClass is what you actually `Dispatch()` - it bundles one or more
interfaces (below) behind a single COM object.

| CoClass | COM name | Default interface | Used here? |
|---|---|---|---|
| `NikonTi2AxAutoConnectMicroscope` | `Nikon.Ti2.AutoConnectMicroscope.1` | `INikonTi2AxMicroscope` | **Yes** - the only one `nis_sdk.py` connects to |
| `NikonTi2AxMicroscope` | `Nikon.Ti2.Microscope.1` | `INikonTi2AxMicroscope` | No (requires an explicit `Connect()` call instead of auto-connecting) |
| `NikonTi2AxObjective` | `Nikon.Ti2.Ax.Objective.1` | `INikonTi2AxObjective` | No - reached indirectly via `microscope.Objective(index)`, never constructed directly |
| `NikonTi2AxSetting` | `Nikon.Ti2.Setting.1` | `INikonTi2AxSetting` | No - reached indirectly via a Microscope property (e.g. `microscope.XPosition`), never constructed directly |
| `NikonTi2AxData` | (data-only variant) | `INikonTi2AxData` | No |

Connection pattern used in this repo (`nis_sdk.py`'s `_ComThread`):

```python
import win32com.client, NkTi2Ax
microscope = win32com.client.Dispatch(NkTi2Ax.NikonTi2AxAutoConnectMicroscope.CLSID)
```

`AutoConnectMicroscope` connects to whatever device is available (real
hardware or the Ti2-E Device Simulator) without an explicit `Connect()`
call - that's the whole reason this CoClass was picked over the plain
`NikonTi2AxMicroscope` one.

## `INikonTi2AxMicroscope` - the main control interface

This is `default_interface` of the CoClass we connect to, and where
almost everything below hangs off `microscope.*`.

### Methods

| Method | Signature | Purpose |
|---|---|---|
| `Connect(uiDeviceIndex)` | `-1`: any microscope, `0`: simulator, `>0`: index in device list | Not called in this repo - `AutoConnectMicroscope` connects implicitly |
| `Disconnect()` | | Not called in this repo - the COM connection lives for the process lifetime (`_ComThread`) |
| `Objective(index)` | property-as-method; `index` is a turret slot (same value as `iNOSEPIECE`) | Returns an `INikonTi2AxObjective` for that slot - used by `pfs_status()`/`nudge_pfs_offset()` in `nis_sdk.py` |
| `SetObjective(index, value)` | | Not used here |
| `DataGet(pVal, DataUsageMask)` / `DataSet(...)` / `DataSetPrepare(...)` | | Bulk read/write of many properties at once, keyed by `DataUsageMask` bitmask - not used here (this repo reads/writes properties individually) |
| `MetadataGet(DataUsageMask)` / `MetadataSet(...)` | | Similar, for metadata - not used here |
| `DedicatedCommand(szCommand, vaArguments)` | | Escape hatch for SDK commands with no dedicated property - not used here |

### Properties - two parallel forms for the same physical setting

Every stage/optics setting is exposed **twice**, confirmed identical by
`acquisition/calibration/nikon_stage_test.py` (see microscope-notes.md):

- **Raw scalar form** - `i`-prefixed (e.g. `iXPOSITION`), a plain
  integer VARIANT, no unit metadata attached. Get/set it directly:
  `microscope.iXPOSITION = 5000`.
- **Setting-object form** - PascalCase (e.g. `XPosition`), returns an
  `INikonTi2AxSetting` object (see below) with the *same* underlying
  value plus range/metadata (`.Lower`, `.Higher`, `.Unit`, `.Scale`,
  `.Control`, `.Enabled`, `.Name`...). Read the value with
  `microscope.XPosition.Value` (or just `microscope.XPosition()` - see
  `INikonTi2AxSetting`'s `__call__`).

`nis_sdk.py` uses **both**: the raw form to actually move the stage
(`m.iXPOSITION = x_counts`), and the Setting-object form purely to read
`.Lower`/`.Higher` for the pre-move travel-limit check. Neither form has
unit metadata that's directly trustworthy (see microscope-notes.md's
"Ti2 ActiveX SDK" section for how X/Y/Z units were empirically derived
instead: 0.1 µm/count for X/Y, 0.01 µm/count for Z).

Grouped by function (raw property / Setting-object property / dispid):

**Stage & focus** (the only group actively driven by this repo, via `nis_sdk.py`'s `XY_GetPosition`/`XY_Move`/`Z_GetPosition`/`Z_Move`):

| Raw property | Setting property | dispid | Notes |
|---|---|---|---|
| `iXPOSITION` | `XPosition` | 16 / 103 | 0.1 µm/count (confirmed) |
| `iYPOSITION` | `YPosition` | 19 / 106 | 0.1 µm/count (confirmed) |
| `iZPOSITION` | `ZPosition` | 13 / 100 | 0.01 µm/count (confirmed) |
| `iXPOSITIONSpeed` / `iYPOSITIONSpeed` / `iZPOSITIONSpeed` | `XPositionSpeed` / `YPositionSpeed` / `ZPositionSpeed` | 17,20,14 / 104,107,101 | Unused here |
| `iXPOSITIONTolerance` / `iYPOSITIONTolerance` / `iZPOSITIONTolerance` | `XPositionTolerance` / ... | 18,21,15 / 105,108,102 | Unused here |
| `iXLimit` / `iYLimit` / `iZLimit` | `XLimit` / `YLimit` / `ZLimit` | 68,69,67 / 152,167,151 | Unused here - `XPosition.Lower/.Higher` (not these) is what `nis_sdk.py` actually checks |
| `iXReset` / `iYReset` / `iZReset` | `XReset` / `YReset` / `ZReset` | 73,74,72 / 155,156,154 | Unused here |
| `iZEscape` | `ZEscape` | 61 / 146 | Unused here |

**Perfect Focus System (PFS)** (used by `nis_sdk.py`'s `pfs_status()`/`nudge_pfs_offset()`):

| Raw property | Setting property | dispid | Notes |
|---|---|---|---|
| `iPFS_SWITCH` | `PfsSwitch` | 48 / 135 | On/off |
| `iPFS_OFFSET` | `PfsOffset` | 49 / 136 | Focus-lock offset, uncalibrated units (see `PFS_MAX_OFFSET_STEP_FRACTION` in `nis_sdk.py`) |
| `iPFS_STATUS` | (none - read via `iPFS_STATUS` only) | 51 | Raw status code |
| `iPFS_DM` | `PfsDm` | 50 / 137 | Unused here |
| — | `Objective(iNOSEPIECE).IsPFSEnabled` | (on `INikonTi2AxObjective`, not Microscope) | Whether PFS is actually engaged - this is where `nudge_pfs_offset()`'s pre-check lives |

**Optics / light path** (used by `nis_sdk.py`'s `get_optical_configuration()`/`apply_optical_configuration()` via `OPTICAL_CONFIG_PROPERTIES`):

| Raw property | Setting property | dispid | Notes |
|---|---|---|---|
| `iNOSEPIECE` | `Nosepiece` | 22 / 109 | Objective turret slot (1-6) - also the index passed to `Objective()` |
| `iDIC_PRISM` / `iDIC_POLARIZER` | `DicPrism` / `DicPolarizer` | 58,59 / 144,145 | |
| `iANALYZER_POS` / `iANALYZER_SLOT` | `AnalyzerPos` / `AnalyzerSlot` | 62,63 / 147,148 | |
| `iLIGHTPATH` | `LightPath` | 30 / 117 | |
| `iCONDENSER` | `Condenser` | 27 / 114 | |
| `iOPTZOOM` | `OpticalZoom` | 60 / 162 | |
| `iTURRET1POS` / `iTURRET1SHUTTER` | `Turret1Pos` / `Turret1Shutter` | 23,24 / 110,111 | Filter turret 1 |
| `iTURRET2POS` / `iTURRET2SHUTTER` | `Turret2Pos` / `Turret2Shutter` | 25,26 / 112,113 | Filter turret 2 |
| `iDLED1..4_POS` / `iDLED1..4_SWITCH` | `DLED1..4Pos` / `DLED1..4Switch` | 95-98,91-94 / 416-419,412-415 | D-LEDI illumination channels 1-4 |
| `iBertrandLens` | `BertrandLens` | 64 / 149 | Unused here |
| `iCORRECTION_COLLAR` / `iCORRECTION_COLLAR_Limit` | `CorrectionCollar` / `CorrectionCollarLimit` | 57,66 / 143,150 | Unused here |
| `iCamera` | `Camera` | 65 / 166 | Unused here - real image capture instead goes through NIS Jobs (`acquisition/backends/nis_jobs_trigger.py`), not this property |
| `iEYEPIECE_TUBEBASECamPort` / `iEYEPIECE_TUBEBASETurret` | `EyePieceTubeBaseCamPort` / `EyePieceTubeBaseTurret` | 52,53 / 138,139 | Unused here |
| `iLAPP_MAINBranch1/2` / `iLAPP_SUBBranch` | `LappMainBranch1/2` / `LappSubBranch` | 54,55,56 / 140,141,142 | Unused here |
| `iMirrorSwitch` | `MirrorSwitch` | 71 / 153 | Unused here |
| `iSHUTTER_DIA` / `iSHUTTER_EPI` / `iSHUTTER_AUX` | `ShutterDia` / `ShutterEpi` / `ShutterAux` | 32,31,33 / 119,118,120 | Unused here |
| `iDIA_LAMP_Pos` / `iDIA_LAMP_Switch` | `DiaLampPos` / `DiaLampSwitch` | 35,34 / 122,121 | Unused here |
| `iINTENSILIGHT_POS/SHUTTER/SWITCH` | `IntensilightPos/Shutter/Switch` | 36,37,38 / 123,124,125 | Unused here |
| `iFILTERWHEEL_BARRIER1/2` | `FilterWheelBarrier1/2` | 28,29 / 115,116 | Unused here |
| `iPWSS_Speed/Switch` / `iPWSA_Speed/Switch` | `PwssSpeed/Switch` / `PwsaSpeed/Switch` | 76,75,78,77 / 158,157,160,159 | Unused here (PWS = presumably a scanning accessory) |
| `iTirf1..3 X/Y POSITION/Speed` | `Tirf1..3X/YPOSITION/Speed` | 79-90 / 400-411 | TIRF module - unused here |

**Bulk/status:**

| Property | dispid | Notes |
|---|---|---|
| `AccessoryMask` | 206 | Unused here |
| `DeviceList` | 201 | Unused here |
| `Settings` | 211 | Unused here - presumably enumerates all Setting objects at once |
| `uiDataUsageMask` | 10 | Unused here |
| `uiIOforTrigger` | 12 | Unused here |
| `uiMicOperationCounter` | 11 | Unused here |

## `INikonTi2AxSetting` - the "child settings object" shape

What every PascalCase Microscope property (e.g. `microscope.XPosition`)
returns. This is the interface `nis_sdk.py` reads `.Lower`/`.Higher` from
for travel-limit checks, and `pfs_status()` reads several diagnostic
fields from (`PfsOffset.Control`, `.Enabled`, `.Unit`, `.Scale`).

| Member | Kind | Purpose |
|---|---|---|
| `Value` | property (also the **default** - `setting()` or `int(setting)` reads it) | The current value, same raw units as the matching `i`-property |
| `Lower` / `Higher` | property | Valid range, in the same raw units - what `nis_sdk.py` checks moves against |
| `Control` | property | Diagnostic - "may indicate whether the SDK currently has write access" per `nis_sdk.py`'s `pfs_status()` comment (unconfirmed) |
| `Enabled` | property | Whether this setting is currently writable/active |
| `Unit` | property | String unit label - not independently verified to be human-meaningful (`nis_sdk.py` derived real units empirically instead) |
| `Scale` | property | Unused here |
| `Name` | property | Short internal name |
| `ProductCode` | property | Unused here |
| `DataUsageMask` / `DataUsageSubMask` / `MetadataUsageMask` | property | Bitmask identifiers - unused here |
| `LongName(value)` / `ShortName(value)` | method (property-as-method) | Human-readable labels |
| `ConvertDev2Phys(value)` / `ConvertPhys2Dev(value)` | method | SDK-native raw-count ⇄ physical-unit conversion - **not used here**; `nis_sdk.py` instead hand-derived its own conversion factors (see microscope-notes.md) since these were never confirmed to return trustworthy physical units |
| `GetConvertParams(Scale, Unit)` | method | Unused here |

## `INikonTi2AxObjective`

Returned by `microscope.Objective(index)`. Used in `nis_sdk.py`'s
`pfs_status()` (`IsPFSEnabled`, `Model`, `Magnification`,
`WorkingDistance`) and its `nudge_pfs_offset()` pre-check
(`IsPFSEnabled`).

| Property | Notes |
|---|---|
| `IsPFSEnabled` | Whether PFS is currently engaged for this objective - used here |
| `Model` | Objective model string - used here |
| `Magnification` | Used here |
| `WorkingDistance` | **Confirmed millimeters** 2026-08-10, cross-referenced against NIS's own `Objectives.xml` catalog - used here |
| `Code` | Unused here |
| `CorrectionCollar` | Unused here |
| `NumericalAperture` | Unused here |
| `ObjectiveType` / `Usage` / `WDType` | Unused here |
| `ObservationMask` | Bitmask of supported observation modes (BF/FL/PH/DIC/DF/...) - see `Ti2_ObservationMask` constants below - unused here |
| `DfModule` / `DicModule(Hr)` / `DicSlider(Hr)` / `ExPhModule` / `NamcModule` / `PhModule` | Per-modality accessory config - unused here |
| `PWS` | Unused here |

## `INikonTi2AxData` - lighter-weight, no live control

Same raw `i`-prefixed property list as `INikonTi2AxMicroscope` (stage,
PFS, optics - all the tables above), but **no** `Connect`/`Disconnect`,
no `Objective()`, and no PascalCase Setting-object properties. Reads and
plain property assignment only - looks like it's meant for
snapshotting/replaying a dataset's device state (paired with
`DataGet`/`DataSet`/`MetadataGet` on the Microscope interface) rather
than interactive control. **Not used anywhere in this repo.**

## Constants / enums (`NkTi2Ax.constants`)

| Enum | Members | Used here? |
|---|---|---|
| `ENikonMicroscopeModel` | `NikonMic_Simulator`(0), `NikonMic_TI2_A/E/EB/U`, `NikonMic_UnKnown`(-1) | No |
| `ENikonTi2AxControl` | `Intelligent`(0), `Motorized`(1), `Manual`(2), `Unmounted`(-1) | No |
| `ENikonTi2AxDedicatedEvent` | ~30 event codes (`Ti2_IsBusy`, `XStageLogicalLimitsEnabled`, `MovingStatus_Changed`, `FuncButtonClicked`, ...) | No - this repo polls (`XY_GetPosition` etc.), it doesn't subscribe to hardware events |
| `ENikonTi2AxGeneralEvent` | `Ti2_DataSetReady/Finished/Aborted`, `Ti2_PFSStatusChanged`, `Ti2_XYStageLogicalLimitsReached`, `Ti2_ZDriveLogicalLimitsReached`, ... | No |
| `ENikonTi2AxIO` | I/O pin bitmasks for the Control Box / Extension Box (blue/green/grey/red per channel) | No |
| `Ti2_DfModule` | `Ti2_DFModule_None/Dry/Oil/DryOil` | No |
| `Ti2_ObservationMask` | Bitmask flags: `BF`, `FL`, `PH`, `DIC`, `NAMC`, `IMSI`, `TIRF`, `EXPH`, `DF` | No |
| `Ti2_PFS` | `Ti2_PFS_UnKnown/Disable/Enable/Enable_Plastic` | No |

None of these are currently imported/used anywhere in this repo (`nis_sdk.py`
reads `IsPFSEnabled` as a plain bool rather than comparing against
`Ti2_PFS_*`) - listed here in case event-driven control (vs. the current
polling model) or richer PFS-state handling is ever added.

## Events interfaces - not used

`_INikonTi2AxEvents` (general/metadata/dedicated/enabled callbacks) and
`_INikonTi2AxObjectiveEvents` exist for subscribing to hardware-initiated
callbacks (e.g. `Ti2_IsBusy`, `MovingStatus_Changed`). This repo's
`_ComThread` (`nis_sdk.py`) does call `pythoncom.PumpWaitingMessages()`
between calls, which *would* be necessary groundwork for these to fire,
but nothing currently subscribes to them - all state is read by polling
(`XY_GetPosition`, `get_pos()` in `mcp_server/loop_tools.py`, etc.), not
by event callback. Worth revisiting if polling ever proves too slow/stale
for a given workflow - this is also exactly the kind of push-based signal
that could back a `stage_revision` counter (see `loop_tools.py`'s header
comment) instead of a home-grown one.

## Legacy `*1`-suffixed interfaces

`INikonTi2AxData1`, `INikonTi2AxMicroscope1`, `INikonTi2AxSetting1` are
near-duplicates of the interfaces above (same members, mostly-different
CLSIDs, occasionally missing a property added in the newer version - e.g.
`INikonTi2AxData1` lacks `iBertrandLens`/`iCamera`/`iCORRECTION_COLLAR*`/
D-LEDI properties that `INikonTi2AxData` has). No CoClass's
`default_interface` points at any of these, and nothing in this repo
references them - almost certainly an older SDK interface version kept
around by `makepy` for COM backward-compatibility, not something to build
against.
