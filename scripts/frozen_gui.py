"""PyInstaller desktop entry point."""

from multiprocessing import freeze_support

from project_name.gui_entry import main

if __name__ == "__main__":
    freeze_support()
    main()
