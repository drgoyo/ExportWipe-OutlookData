"""PyInstaller Streamlit entry point."""

from multiprocessing import freeze_support

from project_name.dashboard_entry import main

if __name__ == "__main__":
    freeze_support()
    main()
