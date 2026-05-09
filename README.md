# ORCA — Open RF Converter & Adapter

Gateway bidireccional open source que conecta **NUNU** (mensajería digital FSK sobre FM en VHF/UHF vía Quansheng UV-K5) con la red mesh **Meshtastic** (LoRa 868 MHz).

Un mensaje enviado desde un UV-K5 con firmware NUNU llega a cualquier nodo Meshtastic, y viceversa, sin modificar ninguno de los dos extremos.

## El problema

Dos ecosistemas mesh digitales incomunicados:

| Red | Medio | Frecuencia | Madurez |
|-----|-------|-----------|---------|
| **NUNU** | FSK sobre FM, BK4819 (UV-K5) | VHF/UHF | Emergente, radioaficionados |
| **Meshtastic** | LoRa | 868 MHz ISM | Consolidada, ciudades UE |

ORCA traduce protocolo entre ambos.

## Arquitectura

```
UV-K5 (NUNU FW) ──► Audio Kenwood 2.5mm ──► ADC/USB ──► nunu_decoder.py
                                                          │
                                                          ▼
                                                    nunu_parser.py
                                                          │
                                                          ▼
                                                    mesh_bridge.py
                                                          │
                                                          ▼
                                               Heltec LoRa 32 V3 ◄──► Meshtastic mesh
```

### Componentes

- **nunu_decoder.py** — Captura audio PCM 44100 Hz, filtra y demodula FSK, detecta syncword `0x30 0x72 0x57 0x6C`
- **nunu_parser.py** — Valida CRC (8 bytes), extrae payload, descarta corruptos
- **mesh_bridge.py** — Routing: prefijo `@alias` → DM, sin prefijo → broadcast. Inyecta vía meshtastic-python
- **capture.py** — Herramienta de captura de audio desde placa USB

### Paquete NUNU (56 bytes)

| Sync (4B) | Header (1B) | Payload (30B) | Nonce (13B) | CRC (8B) |
|-----------|-------------|---------------|-------------|----------|

Header: tipo (bits 7-3) + hop count (bits 2-0, máx 7)

## Estado

**Fase 1 — Decoder Python en PC** (en curso)

- [x] Captura de audio desde USB soundcard
- [ ] Demodulación FSK + syncword detection
- [ ] Validación CRC + extracción payload
- [ ] Bridge con Meshtastic

**Fase 2** — Puerto a C++ en Cardputer (ESP32-S3 + LoRa SPI)

**Fase 3** — Hardware integrado: UV-K5 + Pi Zero 2W + Heltec LoRa en caja ABS

## Dependencias

```bash
pip install sounddevice scipy numpy meshtastic pyserial flask
```

## Referencias

- [Firmware NUNU (kamilsss655)](https://github.com/kamilsss655/uv-k5-firmware-custom)
- [ESPRI — Interfaz hardware Kenwood](https://github.com/kamilsss655/ESPRI)
- [Meshtastic Python API](https://python.meshtastic.org)
- BK4819 datasheet (público)

## Licencia

Open source. Operación bajo indicativo EA3JHL. Sin cifrado ChaCha20 — compatible con RRAE.
