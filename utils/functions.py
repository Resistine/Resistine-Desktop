import customtkinter
import math

def create_option(row, column, container_frame, plugin):
    """
    Create an option frame with an icon, title, status, and status icon, and make it clickable to open the plugin's main screen.
    
    :param row: The row position in the grid.
    :param column: The column position in the grid.
    :param container_frame: The parent frame to contain this option.
    :param plugin: The plugin object containing the icon, name, status, and main screen creation method.
    """
    # Create a frame for the option
    frame = customtkinter.CTkFrame(container_frame, corner_radius=10, fg_color=("gray75", "gray25"))
    frame.grid(row=row, column=column, padx=10, pady=5, sticky="nsew")
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure((1, 1), weight=1)

    # Create a container frame for the main icon and title
    icon_title_frame = customtkinter.CTkFrame(frame, fg_color="transparent")

    # Center the icon_title_frame vertically and horizontally
    icon_title_frame.grid(row=0, column=0, padx=10, pady=(35, 5), sticky="nsew")
    icon_title_frame.grid_columnconfigure(0, weight=1)
    icon_title_frame.grid_rowconfigure(0, weight=1)
    icon_title_frame.grid_rowconfigure(1, weight=1)

    # Main icon
    main_icon_image = plugin.get_icon()
    main_icon_label = customtkinter.CTkLabel(icon_title_frame, image=main_icon_image, text="")
    main_icon_label.grid(row=0, column=0, padx=(10, 10), pady=(5, 5))

    # Title label
    title_label = customtkinter.CTkLabel(icon_title_frame, text=plugin.get_name(), font=customtkinter.CTkFont(size=14, weight="bold"))
    title_label.grid(row=1, column=0, padx=0, pady=5)

    # Status label
    status_label = customtkinter.CTkLabel(icon_title_frame, text=f'Status: {plugin.get_status()}', font=customtkinter.CTkFont(size=12, weight="normal"))
    status_label.grid(row=2, column=0, padx=0, pady=5)

    # Status icon
    icon_status_image = plugin.get_icon_alert()
    icon_status_label = customtkinter.CTkLabel(icon_title_frame, image=icon_status_image, text="")
    icon_status_label.grid(row=3, column=0, padx=(10, 10), pady=(5, 5))

    # Make the entire frame clickable to open the URL
    frame.bind("<Button-1>", lambda event: plugin.create_main_screen().grid(row=0, column=1, sticky="nsew"))
    main_icon_label.bind("<Button-1>", lambda event: plugin.create_main_screen().grid(row=0, column=1, sticky="nsew"))
    title_label.bind("<Button-1>", lambda event: plugin.create_main_screen().grid(row=0, column=1, sticky="nsew"))

def create_tab_button(frame, name, icon, command=None, row=0, col=0):
    """
    Create a button for a tab with the specified name, icon, and command.
    
    :param frame: The parent frame to contain this button.
    :param name: The name to display on the button.
    :param icon: The icon to display on the button.
    :param command: The command to execute when the button is clicked.
    :param row: The row position in the grid.
    :param col: The column position in the grid.
    :return: The created button.
    """
    frame_button = customtkinter.CTkButton(frame, corner_radius=0, height=40, border_spacing=10, text=name,
                                           fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                                           image=icon, anchor="w", command=command)
    frame_button.grid(row=row, column=col, sticky="ew")

    return frame_button

def create_grid(frame, row, column, plugins, color, sticky="nsew"):
    """
    Create a grid layout for the plugins with the specified color and sticky option.
    
    :param frame: The parent frame to contain this grid.
    :param row: The row position in the grid.
    :param column: The column position in the grid.
    :param plugins: The list of plugins to display in the grid.
    :param color: The background color of the grid.
    :param sticky: The sticky option for the grid.
    :return: The created grid frame.
    """
    rows_tuple, cols_tuple = calculate_rows_cols(len(plugins))
    frame = customtkinter.CTkFrame(frame, corner_radius=0, fg_color=color)
    frame.grid(row=row, column=column, sticky=sticky)
    frame.grid_columnconfigure(rows_tuple, weight=1)
    frame.grid_rowconfigure(cols_tuple, weight=1)

    # Create the grid and color the columns
    for r in rows_tuple:
        for c in cols_tuple:
            cell_frame = customtkinter.CTkFrame(frame, corner_radius=0, fg_color="transparent")
            cell_frame.grid(row=r, column=c, sticky="nsew")
            frame.grid_columnconfigure(c, weight=1)
            frame.grid_rowconfigure(r, weight=1)
    return frame

def calculate_rows_cols(num_plugins):
    """
    Calculate the number of rows and columns needed to display the plugins in a grid.
    
    :param num_plugins: The total number of plugins.
    :return: A tuple containing the range of rows and columns.
    """
    cols = math.ceil(math.sqrt(num_plugins))
    rows = math.ceil(num_plugins / cols)
    return tuple(range(rows)), tuple(range(cols))