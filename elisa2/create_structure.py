import os

# Root directory
root = "F:/ELISA/ELISA_Platform/elisa2"

# Folder + file structure
structure = {
    "config": [
        "settings.py",
        "agronomy.yaml"
    ],
    "ingestion": [
        "gee_client.py",
        "gee_extractor.py",
        "era5_loader.py",
        "nasa_power.py",
        "pipeline.py"
    ],
    "features": [
        "crop_calendar.py",
        "eto.py",
        "soil_balance.py",
        "builder.py"
    ],
    "models/patchtst": [
        "model.py",
        "dataset.py",
        "trainer.py"
    ],
    "models/downscaler": [
        "rf_model.py",
        "trainer.py"
    ],
    "decision": [
        "tariff.py",
        "state_manager.py",
        "mpc.py"
    ],
    "simulation": [
        "farmer_blind.py",
        "farmer_minor.py",
        "farmer_major.py",
        "metrics.py",
        "compare.py"
    ],
    "farm": [
        "geocoder.py",
        "manager.py"
    ],
    "dashboard": [
        "app.py"
    ],
    "pipelines": [
        "run.py"
    ]
}

def create_structure(base_path, structure_dict):
    for folder, files in structure_dict.items():
        folder_path = os.path.join(base_path, folder)
        
        # Create directory (including nested ones)
        os.makedirs(folder_path, exist_ok=True)
        
        for file in files:
            file_path = os.path.join(folder_path, file)
            
            # Create empty file if it doesn't exist
            if not os.path.exists(file_path):
                with open(file_path, "w") as f:
                    f.write(f"# {file}\n")

def main():
    os.makedirs(root, exist_ok=True)
    create_structure(root, structure)
    print(f"✅ Project structure '{root}/' created successfully!")

if __name__ == "__main__":
    main()