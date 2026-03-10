import geopandas as gpd
import requests
from shapely.geometry import Point

ISS_URL = "http://api.open-notify.org/iss-now.json"
MAP_URL = "https://nominatim.openstreetmap.org/reverse"

iho = None


def get_iss_lat_lon() -> tuple[float, float] | None:
    r = requests.get(ISS_URL, timeout=30)
    r.raise_for_status()
    obj = r.json()

    if obj["message"] == "success":
        latitude = obj["iss_position"]["latitude"]
        longitude = obj["iss_position"]["longitude"]
        return latitude, longitude

    return None


def get_ocean(latitude: float, longitude: float) -> str | None:
    global iho
    if not iho:
        # lazy load IHO
        print("[INFO] Loading map file, this may take a bit...")
        iho = gpd.read_file("World_Seas_IHO_v3/World_Seas_IHO_v3.shp")

    point = Point(longitude, latitude)
    hit = iho[iho.contains(point)]

    if not hit.empty:
        row = hit.iloc[0]
        return row.get("NAME")

    return None


def get_address(latitude: float, longitude: float) -> str | None:
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "jsonv2",
        "addressdetails": 1,
        "accept-language": "en",
        "zoom": 10,
        "extratags": 1,
    }

    headers = {"User-Agent": "iss-chatbot (crwolff@calpoly.edu)"}
    r = requests.get(MAP_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()

    if "error" not in data:
        addr = data.get("address", {})
        city = (
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("hamlet")
        )
        state = addr.get("state")
        country = addr.get("country")

        if city and state and country:
            return ", ".join([city, state, country])
        else:
            return data.get("display_name")

    return None


def main() -> None:
    lat_lon = get_iss_lat_lon()

    if not lat_lon:
        print("Cannot find ISS.")
        return

    lat, lon = lat_lon
    address = get_address(lat, lon)
    if address:
        print(f"ISS above: {address}")
    else:
        ocean = get_ocean(lat, lon)
        if not ocean:
            print(f"ISS at: {lat}, {lon}")
        else:
            print(f"ISS above: {ocean}")


if __name__ == "__main__":
    main()
