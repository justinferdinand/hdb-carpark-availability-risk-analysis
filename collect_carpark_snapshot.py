import os
import requests
import pandas as pd
import folium

from datetime import datetime
from zoneinfo import ZoneInfo
from pyproj import Transformer


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.path.join(PROJECT_ROOT, "data")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "outputs")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

MASTER_PATH = os.path.join(DATA_DIR, "carpark_snapshots_master.csv")
CARPARK_INFO_PATH = os.path.join(PROJECT_ROOT, "HDBCarparkInformation.csv")


def classify_risk(rate):
    if rate < 0.10:
        return "High Risk"
    elif rate < 0.30:
        return "Medium Risk"
    else:
        return "Low Risk"


def risk_color(risk):
    if risk == "High Risk":
        return "red"
    elif risk == "Medium Risk":
        return "orange"
    else:
        return "green"


def create_maps(carpark_df, carpark_info, timestamp, retrieved_time, snapshot_folder):
    merged_map_df = carpark_df.merge(
        carpark_info,
        left_on="carpark_number",
        right_on="car_park_no",
        how="left"
    )

    merged_map_df["x_coord"] = pd.to_numeric(merged_map_df["x_coord"], errors="coerce")
    merged_map_df["y_coord"] = pd.to_numeric(merged_map_df["y_coord"], errors="coerce")

    map_df = merged_map_df.dropna(subset=["x_coord", "y_coord"]).copy()

    transformer = Transformer.from_crs("EPSG:3414", "EPSG:4326", always_xy=True)

    map_df["longitude"], map_df["latitude"] = transformer.transform(
        map_df["x_coord"].values,
        map_df["y_coord"].values
    )

    # Full map
    full_map = folium.Map(
        location=[1.3521, 103.8198],
        zoom_start=12,
        tiles="CartoDB positron"
    )

    for _, row in map_df.iterrows():
        popup_text = f"""
        <b>Carpark:</b> {row['carpark_number']}<br>
        <b>Address:</b> {row['address']}<br>
        <b>Total Lots:</b> {row['total_lots']}<br>
        <b>Lots Available:</b> {row['lots_available']}<br>
        <b>Availability Rate:</b> {row['availability_rate']:.1%}<br>
        <b>Parking Pressure:</b> {row['parking_pressure']:.1%}<br>
        <b>Risk:</b> {row['risk_category']}<br>
        <b>Retrieved:</b> {retrieved_time.strftime("%Y-%m-%d %H:%M")}
        """

        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=1.5,
            popup=folium.Popup(popup_text, max_width=300),
            color=risk_color(row["risk_category"]),
            fill=True,
            fill_color=risk_color(row["risk_category"]),
            fill_opacity=0.45
        ).add_to(full_map)

    all_map_path = os.path.join(
        snapshot_folder,
        f"all_carpark_risk_map_{timestamp}.html"
    )

    full_map.save(all_map_path)

    # High-risk map
    high_risk_map_df = map_df[map_df["risk_category"] == "High Risk"].copy()

    high_risk_map = folium.Map(
        location=[1.3521, 103.8198],
        zoom_start=12,
        tiles="CartoDB positron"
    )

    for _, row in high_risk_map_df.iterrows():
        popup_text = f"""
        <b>Carpark:</b> {row['carpark_number']}<br>
        <b>Address:</b> {row['address']}<br>
        <b>Total Lots:</b> {row['total_lots']}<br>
        <b>Lots Available:</b> {row['lots_available']}<br>
        <b>Availability Rate:</b> {row['availability_rate']:.1%}<br>
        <b>Parking Pressure:</b> {row['parking_pressure']:.1%}<br>
        <b>Risk:</b> {row['risk_category']}<br>
        <b>Retrieved:</b> {retrieved_time.strftime("%Y-%m-%d %H:%M")}
        """

        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=3,
            popup=folium.Popup(popup_text, max_width=300),
            color="red",
            fill=True,
            fill_color="red",
            fill_opacity=0.7
        ).add_to(high_risk_map)

    high_risk_map_path = os.path.join(
        snapshot_folder,
        f"high_risk_carpark_map_{timestamp}.html"
    )

    high_risk_map.save(high_risk_map_path)


def collect_carpark_snapshot():
    if not os.path.exists(CARPARK_INFO_PATH):
        raise FileNotFoundError(
            "HDBCarparkInformation.csv is missing. Put it in the repository root."
        )

    carpark_info = pd.read_csv(CARPARK_INFO_PATH)

    url = "https://api.data.gov.sg/v1/transport/carpark-availability"

    response = requests.get(url, timeout=30)
    response.raise_for_status()

    data = response.json()
    records = data["items"][0]["carpark_data"]

    expanded_rows = []

    for item in records:
        carpark_number = item["carpark_number"]
        update_datetime = item["update_datetime"]

        for info in item["carpark_info"]:
            expanded_rows.append({
                "carpark_number": carpark_number,
                "update_datetime": update_datetime,
                "total_lots": info["total_lots"],
                "lots_available": info["lots_available"],
                "lot_type": info["lot_type"]
            })

    carpark_df = pd.DataFrame(expanded_rows)

    carpark_df = carpark_df[carpark_df["lot_type"] == "C"].copy()

    carpark_df["total_lots"] = pd.to_numeric(carpark_df["total_lots"], errors="coerce")
    carpark_df["lots_available"] = pd.to_numeric(carpark_df["lots_available"], errors="coerce")

    carpark_df = carpark_df.dropna(subset=["total_lots", "lots_available"])
    carpark_df = carpark_df[carpark_df["total_lots"] > 0].copy()

    carpark_df["availability_rate"] = (
        carpark_df["lots_available"] / carpark_df["total_lots"]
    )

    carpark_df["parking_pressure"] = 1 - carpark_df["availability_rate"]
    carpark_df["risk_category"] = carpark_df["availability_rate"].apply(classify_risk)

    retrieved_time = datetime.now(ZoneInfo("Asia/Singapore"))
    timestamp = retrieved_time.strftime("%Y%m%d_%H%M")

    carpark_df["retrieved_at"] = retrieved_time.strftime("%Y-%m-%d %H:%M:%S")

    snapshot_folder = os.path.join(OUTPUT_DIR, timestamp)
    os.makedirs(snapshot_folder, exist_ok=True)

    snapshot_path = os.path.join(
        snapshot_folder,
        f"carpark_snapshot_{timestamp}.csv"
    )

    carpark_df.to_csv(snapshot_path, index=False)

    carpark_df.to_csv(
        MASTER_PATH,
        mode="a",
        header=not os.path.exists(MASTER_PATH),
        index=False
    )

    create_maps(
        carpark_df=carpark_df,
        carpark_info=carpark_info,
        timestamp=timestamp,
        retrieved_time=retrieved_time,
        snapshot_folder=snapshot_folder
    )

    print(f"Collected snapshot at Singapore time: {retrieved_time}")
    print(f"Rows collected: {len(carpark_df)}")
    print(f"Saved snapshot: {snapshot_path}")
    print(f"Updated master file: {MASTER_PATH}")


if __name__ == "__main__":
    collect_carpark_snapshot()
