# Orientation input (Z8 lab)

The Z8 lab's ch3/address-0x1d diagnostic orientation peer supplies six
big-endian 16-bit XYZ sample words (1 g = 0x4000 on the 1/16384 scale), the
format the firmware's sensor polling consumes. Until the runtime
`orientation-input` property is set, the peer keeps feeding the stationary
reset vector, byte for byte; the property is default off and purely additive
instrumentation for dynamic pose injection.

```sh
# QMP
{"execute":"qom-set","arguments":{"path":"/machine","property":"orientation-input","value":"000040000000"}}
```

Bytes are consumed only when a guest read starts, so changing the pose cannot
overwrite an in-flight FIFO or synthesize an IRQ; the readonly
`orientation-state` property reports the effective sample.

## Camera-verified axis assignment and pose table

The chip axis meanings below are camera evidence, not a guess: the
NikonFirmwarePatch `video-orientation` feature classifies this same gravity
vector on the camera, and the tkhd rotation matrices of takes recorded in
each grip identify which lane fired (the portrait pair settled the direction
order in a second camera round). Chip X is the camera vertical axis with the
sign inverted, chip Y is the roll axis, and chip Z is the lens axis.

| Pose | Property value (BE16 XYZ) | Vector | Camera grip |
| --- | --- | --- | --- |
| `landscape` | `c00000000000` | X = -1 g | level landscape grip, no rotation mark |
| `upsidedown` | `400000000000` | X = +1 g | landscape rolled 180 degrees |
| `portraitA` | `000040000000` | Y = +1 g | portrait, shutter-bottom (90 deg CW mark) |
| `portraitB` | `0000c0000000` | Y = -1 g | portrait, shutter-top (90 deg CCW mark) |
| `lensup` | `000000004000` | Z = +1 g | lens straight up; the stationary default |
| `lensdown` | `00000000c000` | Z = -1 g | lens straight down |

The unset default equals `lensup`: the stationary reset vector (0, 0, 1024)
left-justified into the six sample bytes. A pose whose dominant axis is Z
carries no roll information (no orientation mark on the camera either); the
firmware-side classifier additionally requires the dominant axis to reach
0.70 g before it reports a code.
