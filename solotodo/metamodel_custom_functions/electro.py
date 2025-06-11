from metamodel.models import MetaModel
from .utils import pretty_dimensions, format_optional_field


def pretty_video_ports(elastic_search_original):
    video_ports = elastic_search_original["video_ports"]
    if video_ports:
        return " | ".join(vp["unicode"] for vp in video_ports)
    else:
        return "No posee"


def additional_es_fields(elastic_search_original, model_name):
    m = model_name
    big_value = 1000 * 1000 * 1000 * 100000
    result = {}
    if m == "Television":
        result["pretty_usb_ports"] = format_optional_field(
            elastic_search_original["usb_ports"], value_if_false="No posee"
        )
        result["pretty_video_ports"] = pretty_video_ports(elastic_search_original)
        result["model_name"] = "{} {}".format(
            elastic_search_original["line_name"],
            elastic_search_original["commercial_model"],
        ).strip()
        result["brand_unicode"] = elastic_search_original["line_brand_unicode"]

        tags = []
        if elastic_search_original["display_unicode"] != "LED":
            tags.append(elastic_search_original["display_unicode"])
        result["tags"] = tags

        return result

    if m == "ExternalStorageDrive":
        result["pretty_weight"] = format_optional_field(
            elastic_search_original["weight"], "g"
        )

        return result

    if m == "MemoryCard":
        result["pretty_part_number"] = format_optional_field(
            elastic_search_original["part_number"]
        )
        return result

    if m == "OpticalDiskPlayer":
        result["pretty_usb_ports"] = format_optional_field(
            elastic_search_original["usb_ports"], value_if_false="No posee"
        )
        return result

    if m == "Oven":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        result["pretty_capacity"] = format_optional_field(
            elastic_search_original["capacity"], "L"
        )
        return result

    if m == "Refrigerator":
        result["pretty_refrigerator_capacity"] = format_optional_field(
            elastic_search_original["refrigerator_capacity"], "L"
        )
        result["pretty_freezer_capacity"] = format_optional_field(
            elastic_search_original["freezer_capacity"], "L"
        )
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        result["pretty_weight"] = format_optional_field(
            elastic_search_original["weight"], "kg"
        )

        total_capacity = (
            elastic_search_original["refrigerator_capacity"]
            + elastic_search_original["freezer_capacity"]
        )

        result["total_capacity"] = total_capacity
        result["pretty_total_capacity"] = format_optional_field(total_capacity, "L.")

        consumption = elastic_search_original["consumption"]
        result["pretty_consumption"] = format_optional_field(consumption, "kWh/mes")
        if consumption > 0:
            result["sorting_consumption"] = consumption
        else:
            result["sorting_consumption"] = big_value

        warnings = []

        if (
            "refrigerador" in elastic_search_original["type_unicode"].lower()
            and elastic_search_original["frosting_unicode"] == "Frío Directo"
        ):
            warnings.append(
                "Los refrigeradores de Frío Directo tienden "
                "a formar hielo que se debe descongelar "
                "manualmente, además de ser menos "
                "eficientes que los No Frost."
            )

        result["warnings"] = warnings

        return result

    if m == "UsbFlashDrive":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        result["pretty_part_number"] = format_optional_field(
            elastic_search_original["part_number"]
        )

        read_speed = elastic_search_original["read_speed"]
        result["pretty_read_speed"] = format_optional_field(read_speed, "MB/s")

        write_speed = elastic_search_original["write_speed"]
        result["pretty_write_speed"] = format_optional_field(write_speed, "MB/s")

        return result

    if m == "VacuumCleaner":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        result["pretty_weight"] = format_optional_field(
            elastic_search_original["weight"], "g"
        )

        return result

    if m == "WashingMachine":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        result["pretty_weight"] = format_optional_field(
            elastic_search_original["weight"], "g"
        )
        weight = elastic_search_original["weight"]
        if weight > 0:
            result["pretty_weight"] = "{} kg.".format(0.001 * weight)
        else:
            result["pretty_weight"] = "Desconocido"

        return result
    if m == "AirConditioner":
        result["pretty_inner_dimensions"] = pretty_dimensions(
            elastic_search_original, ["inner_width", "inner_height", "inner_depth"]
        )
        result["pretty_outer_dimensions"] = pretty_dimensions(
            elastic_search_original, ["outer_width", "outer_height", "outer_depth"]
        )
    if m == "WaterHeater":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        return result

    if m == "Stove":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)
        result["pretty_weight"] = format_optional_field(
            elastic_search_original["weight"], "g"
        )
        return result

    if m == "SpaceHeater":
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)

        unified_power = 0
        if elastic_search_original["power_w"]:
            unified_power = elastic_search_original["power_w"]
        elif elastic_search_original["power_kcal_hr"]:
            unified_power = int(elastic_search_original["power_kcal_hr"] * 1.16222222)
        elif elastic_search_original["power_btu_hr"]:
            unified_power = int(elastic_search_original["power_btu_hr"] * 0.29307107)

        result["unified_power"] = unified_power
        return result
    if m == "VideoGameConsole":
        result["brand_unicode"] = elastic_search_original[
            "c_model_base_model_family_brand_unicode"
        ]
        return result
    if m == "AllInOne":
        storage_unicodes = []

        for sd in elastic_search_original["storage_drives"]:
            storage_unicodes.append(sd["unicode"])

            result["storage_unicode"] = " + ".join(storage_unicodes)
        return result
    if m == "Tablet":
        result["base_model_internal_storage_cell_connectivity_key"] = (
            elastic_search_original["base_model_id"]
            + 10 * elastic_search_original["internal_storage_id"]
            + 100 * elastic_search_original["cell_connectivity_id"]
        )
        result["default_bucket"] = result[
            "base_model_internal_storage_cell_connectivity_key"
        ]

        result["pretty_dimensions"] = pretty_dimensions(
            elastic_search_original, ["length", "width", "depth"]
        )
        battery_mah = elastic_search_original["battery_mah"]
        result["pretty_battery"] = format_optional_field(battery_mah, "mAh")
        result["model_name"] = "{} {}".format(
            elastic_search_original["line_name"],
            elastic_search_original["commercial_model"],
        ).strip()

        # General score computation
        scores = []

        # Maxes based on current A12X Bionic scores (March 2020)
        score_fields = [
            ("geekbench_44_single_core_score", 5000),
            ("geekbench_44_multi_core_score", 18000),
            ("geekbench_5_single_core_score", 1200),
            ("geekbench_5_multi_core_score", 4700),
            ("passmark_score", 760000),
        ]

        for score_field, max_score in score_fields:
            field_name = "soc_" + score_field

            if not elastic_search_original.get(field_name):
                continue

            relative_score = int(
                1000 * elastic_search_original.get(field_name, 0) / max_score
            )

            if relative_score > 1000:
                relative_score = 1000

            scores.append(relative_score)

        if scores:
            general_score = int(sum(scores) / len(scores))
        else:
            general_score = 0

        result["general_score"] = general_score

        has_cell_connectivity = (
            elastic_search_original["cell_connectivity_unicode"] != "No"
        )
        result["has_cell_connectivity"] = has_cell_connectivity

        tags = []
        if has_cell_connectivity:
            tags.append(elastic_search_original["cell_connectivity_unicode"])
        result["tags"] = tags

        warnings = []

        if elastic_search_original["operating_system_line_is_discontinued"]:
            warnings.append(
                "El sistema operativo con el que esta tablet "
                "fue lanzado está obsoleto. Por favor "
                "verifique si es que tiene disponible una "
                "actualización de software reciente antes "
                "de comprarla"
            )

        if elastic_search_original["line_brand_unicode"] == "Huawei":
            warnings.append(
                "Las tablets Huawei no tienen disponibles las "
                "aplicaciones de Google (Youtube, GMail, etc) "
                "ni acceso a la Play Store."
            )
        if "Android Go" in elastic_search_original["operating_system_unicode"]:
            warnings.append(
                'Este equipo viene con Android "Go" como sistema '
                "operativo, que es más básico y limitado que "
                "Android tradicional"
            )
        if elastic_search_original["ram_value"] < 3072:
            warnings.append(
                "Este equipo solo tiene {} de RAM. SoloTodo "
                "recomienda equipos con por lo menos 3 GB de RAM "
                "para una tablet actual.".format(elastic_search_original["ram_unicode"])
            )
        if elastic_search_original["internal_storage_value"] < 32:
            warnings.append(
                "Esta tablet solo tiene {} de memoria. SoloTodo "
                "recomienda equipos con por lo menos 32 GB de "
                "almacenamiento para una tablet actual.".format(
                    elastic_search_original["internal_storage_unicode"]
                )
            )

        result["warnings"] = warnings

        return result

    if m == "Wearable":
        if elastic_search_original["weight"]:
            pretty_weight = "{} g.".format(elastic_search_original["weight"])
        else:
            pretty_weight = "Desconocido"

        result["pretty_weight"] = pretty_weight

        if elastic_search_original["battery_mah"]:
            pretty_battery_mah = "{} mAh".format(elastic_search_original["battery_mah"])
        else:
            pretty_battery_mah = "Desconocido"

        result["pretty_battery_mah"] = pretty_battery_mah
        result["pretty_dimensions"] = pretty_dimensions(elastic_search_original)

    return result


def unicode_function(im):
    m = MetaModel.get_model_by_id(im.model_id).name
    if m == "LightTube":
        specs = [str(im.l_type)]

        if im.consumption:
            if im.equivalent_power:
                specs.append(
                    "{} - {}W".format(
                        im.consumption.quantize(0), im.equivalent_power.quantize(0)
                    )
                )
            else:
                specs.append("{}W".format(im.consumption.quantize(0)))
        else:
            if im.equivalent_power:
                specs.append("{}W Equivalente".format(im.equivalent_power.quantize(0)))

        specs.append(str(im.light_type))
        specs.append(str(im.length))

        name_value = im.name
        if name_value is None:
            name_value = ""

        result = "{} {} {} ({})".format(
            im.technology, im.brand, name_value, " / ".join(specs)
        )
        return " ".join(result.split())
    if m == "LightProjector":
        specs = []

        if im.consumption:
            if im.equivalent_power:
                specs.append(
                    "{} - {}W".format(
                        im.consumption.quantize(0), im.equivalent_power.quantize(0)
                    )
                )
            else:
                specs.append("{}W".format(im.consumption.quantize(0)))
        else:
            if im.equivalent_power:
                specs.append("{}W Equivalente".format(im.equivalent_power.quantize(0)))

        specs.append(str(im.light_type))

        if im.has_movement_sensor:
            specs.append("Con sensor de movimimiento")

        name_value = im.name
        if name_value is None:
            name_value = ""

        result = "{} {} {} ({})".format(
            im.technology, im.brand, name_value, " / ".join(specs)
        )
        return " ".join(result.split())
    if m == "Lamp":
        specs = [str(im.socket), im.format.short_name]

        if im.consumption:
            if im.equivalent_power:
                specs.append(
                    "{} - {}W".format(
                        im.consumption.quantize(0), im.equivalent_power.quantize(0)
                    )
                )
            else:
                specs.append("{}W".format(im.consumption.quantize(0)))
        else:
            if im.equivalent_power:
                specs.append("{}W Equivalente".format(im.equivalent_power.quantize(0)))

        specs.append(str(im.light_type))

        name_value = im.name
        if name_value is None:
            name_value = ""

        result = "{} {} {} ({})".format(
            im.l_type, im.brand, name_value, " / ".join(specs)
        )
        return " ".join(result.split())
    if m == "MemoryCardCapacity":
        if im.value % 1000 == 0:
            return "{} TB".format(im.value / 1000)
        elif im.value > 1000 and (im.value - 500) % 1000 == 0:
            return "{}.5 TB".format((im.value - 500) / 1000)
        else:
            return "{} GB".format(im.value)
    if m == "MemoryCard":
        result = "{} {} {}".format(im.line, im.type, im.capacity)

        if im.rated_speed.value:
            result += " {}".format(im.rated_speed)
        elif im.x_speed.value:
            result += " {}".format(im.x_speed)

        if im.part_number:
            result += " ({})".format(im.part_number)

        return result
    if m == "UsbFlashDriveCapacity":
        if im.value % 1000 == 0:
            return "{} TB".format(im.value / 1000)
        elif im.value > 1000 and (im.value - 500) % 1000 == 0:
            return "{}.5 TB".format((im.value - 500) / 1000)
        else:
            return "{} GB".format(im.value)
