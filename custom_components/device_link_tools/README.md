# Device link tools

Actions to attach an existing entity to an existing device, which the Home Assistant UI
does not let you do. Useful for entities created by integrations that have no
device-linking option of their own — `rest`, `command_line`, `scrape`, `sql` — which
would otherwise sit outside any device.

The integration creates no entities. It only registers four actions.

## Installation

Copy `device_link_tools` into your `<config>/custom_components/` directory and restart
Home Assistant, then add the integration from **Settings → Devices & services → Add
integration → Device link tools**. There is nothing to configure; the entry only exists
so the integration is manageable from the UI.

To run it from this repository's development instance instead:

```bash
ln -s ../../custom_components/device_link_tools config/custom_components/
python -m homeassistant -c ./config
```

`python -m homeassistant` puts the repository root on `sys.path`, which is what makes the
repository-level `custom_components` directory visible; the `hass` console script does
not.

## Actions

### `device_link_tools.read_identifiers`

Reads the identifiers of the device an entity is currently linked to. Returns a response,
so it needs a `response_variable` in a script.

```yaml
action: device_link_tools.read_identifiers
data:
  entity_id: sensor.boiler_temperature
response_variable: link
```

```yaml
entity_id: sensor.boiler_temperature
device_id: 9f2c1e...
identifiers:
  - ["mqtt", "8848_5"]
connections:
  - ["mac", "aa:bb:cc:dd:ee:ff"]
name: Boiler
```

`device_id` is `null` and `identifiers` empty when the entity is not linked to anything.

### `device_link_tools.add_identifier`

Links one or more entities to the device carrying the given identifiers.

```yaml
action: device_link_tools.add_identifier
data:
  entity_id:
    - sensor.solar_power
    - sensor.grid_import
  identifiers: mqtt:8848_5
```

Identifiers can be written in any of these forms:

```yaml
identifiers: mqtt:8848_5
identifiers: { mqtt: "8848_5" }
identifiers: [["mqtt", "8848_5"]]
identifiers: [{ domain: mqtt, identifier: "8848_5" }]
```

### `device_link_tools.remove_identifier`

Unlinks entities from their device.

```yaml
action: device_link_tools.remove_identifier
data:
  entity_id: sensor.solar_power
```

### `device_link_tools.clone`

Copies the device link of a source entity onto other entities, so you do not have to read
and retype the identifiers.

```yaml
action: device_link_tools.clone
data:
  source_entity_id: sensor.boiler_temperature
  target_entity_id:
    - sensor.solar_power
    - sensor.grid_import
```

The three mutating actions are admin-only. Automations and scripts run without a user
context and are unaffected.

## Links survive restarts

An entity platform passes the device it knows about — or `None` — to the entity registry
every time it adds an entity, so the owning integration resets a manually set link on
every restart and on every reload of its config entry.

Every link made through these actions is therefore recorded in the config entry options
and re-applied when Home Assistant has started, and again whenever the registry clears
it. The re-application only fills in an empty link: if the owning integration sets a
device itself, that choice wins and nothing is overwritten. `remove_identifier` deletes
the recorded link, so an entity you unlink stays unlinked.

## Limitations

- **The entity must have a unique ID.** Entities without one never enter the entity
  registry and cannot be linked to a device by any means. For a YAML `rest` or
  `command_line` sensor, add `unique_id:` to its configuration and reload it.
- The integration writes to Home Assistant's internal registries. These APIs are not
  covered by any stability guarantee across major versions.
- Between Home Assistant starting and the re-application pass, an entity is briefly
  unlinked. An automation that triggers on area membership during startup can see the
  gap.

## What linking to a device changes

Beyond appearing on the device page, a linked entity follows the device
(`homeassistant/helpers/entity_registry.py`, `async_device_modified`):

- **Device deleted** — the entity is *not* deleted. It does not belong to the device's
  config entry, so it is only unlinked.
- **Device disabled** — the entity is disabled too, and stops working.
- **Device renamed** — an entity whose name is not device-derived
  (`has_entity_name: false`, the usual case for REST and template YAML sensors) has its
  name rewritten with the device name as a prefix.
- **Area** — an entity with no area of its own inherits the device's area, and becomes
  reachable by area-based targeting.

There is no domain to respect: a Home Assistant device is not typed and routinely holds
entities from several domains. Attaching a `sensor` to a device that also carries a
`light` is normal, not a workaround.

History and statistics in `home-assistant_v2.db` are untouched — only the structural link
changes.

## Development notes

`strings.json` is the English source; `translations/en.json` is a copy of it. Only the
files under `translations/` are read at runtime, and `[%key:...%]` references are not
expanded for custom integrations, so both files carry literal text. Keep them in sync
when editing.

Tests live in `tests/custom_components/device_link_tools/`:

```bash
uv run pytest tests/custom_components/device_link_tools
```
