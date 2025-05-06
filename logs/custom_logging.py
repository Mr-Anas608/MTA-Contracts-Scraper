"""
Logging Utility for YouTube Scraper

Provides a function to set up logging with configurable levels for console and file output,
featuring a custom formatter for visually distinct console logs.
"""
import logging
import os
import re
from typing import Optional

# --- Custom Formatter for Console Output ---

# Replace the existing PrettyFormatter class with this one:

class PrettyFormatter(logging.Formatter):
    """Formats logs with color, dynamic borders, and centered messages for the console."""

    COLORS = {
        'DEBUG': '\033[94m',    # Blue
        'INFO': '\033[92m',     # Green
        'WARNING': '\033[93m',  # Yellow
        'ERROR': '\033[91m',    # Red
        'CRITICAL': '\033[95m', # Purple
        'ENDC': '\033[0m'       # Reset color
    }
    MIN_BORDER_WIDTH = 40 # Minimum width for the border
    PADDING = 2 # Spaces inside border on each side

    def format(self, record):
        # Use a basic formatter to get the raw message
        log_fmt = '%(message)s'
        basic_formatter = logging.Formatter(log_fmt)
        message = basic_formatter.format(record)

        # --- Prepare components and calculate lengths ---
        level_color = self.COLORS.get(record.levelname, '')
        reset_color = self.COLORS['ENDC']

        # Create colored prefix, e.g., "[INFO]"
        level_prefix_text = f"[{record.levelname}]"
        colored_prefix = f"{level_color}{level_prefix_text}{reset_color}" if level_color else level_prefix_text
        prefix_len = len(level_prefix_text) # Length of the text part of the prefix

        # Get the displayable message content (remove color codes if any were in original message)
        ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
        displayed_content = ansi_escape.sub('', message)
        content_len = len(displayed_content)

        # --- Calculate total width and border ---
        # Total visible width needed: Prefix + 1 space + Message Content
        total_content_width = prefix_len + 1 + content_len
        # Border needs to encompass content + padding on both sides
        border_len = max(total_content_width + (self.PADDING * 2), self.MIN_BORDER_WIDTH)
        border = '=' * border_len

        # --- Construct the content line ---
        # Calculate remaining space within the border for padding around the content
        available_space = border_len - (self.PADDING * 2)
        padding_needed = available_space - total_content_width
        # Distribute padding (can be uneven if padding_needed is odd)
        pad_left = padding_needed // 2
        pad_right = padding_needed - pad_left

        # Apply color to the main message content
        colored_content = f"{level_color}{displayed_content}{reset_color}" if level_color else displayed_content

        # Build the final line within the borders
        # Padding(L) + Prefix + Space + Content + Padding(R)
        inner_line = f"{' ' * pad_left}{colored_prefix} {colored_content}{' ' * pad_right}"

        # Ensure the constructed inner_line fits within the available space, accounting for color codes
        # This part is tricky; the easiest way is often to rely on the length calculations being correct
        # and let the terminal handle rendering. A precise check would involve recalculating visible length
        # of `inner_line`, but let's try the simpler calculation first.

        # Add the outer padding inside the border
        final_line_content = f"{' ' * self.PADDING}{inner_line}{' ' * self.PADDING}"


        # Assemble final output
        return f"\n{border}\n{final_line_content}\n{border}\n"

# --- Logging Setup Function ---

def setup_logging(
    logger_name: str = "YouTubeScraper",
    log_file: str = "scraper.log",
    console_level: int = logging.INFO, # Default level for console output
    file_level: int = logging.DEBUG,    # Default level for file output
    save_log: bool = True,
    log_dir: str = r"Logs\General_Logs" # Default log directory
) -> logging.Logger:
    """
    Configures a logger with specified levels for console and file handlers.

    Ensures handlers are added only once for the given logger name.

    Args:
        logger_name (str): The name for the logger instance.
        log_file (str): Base name for the log file (used if save_log is True).
        console_level (int): Logging level for console output (e.g., logging.INFO).
        file_level (int): Logging level for file output (e.g., logging.DEBUG).
        save_log (bool): If True, enables saving logs to a file.
        log_dir (str): Directory where the log file will be saved.

    Returns:
        logging.Logger: The configured logger instance.
    """
    logger = logging.getLogger(logger_name)

    # Configure only if logger has no handlers to prevent duplication
    if not logger.handlers:
        # Set logger's base level to the minimum of its handlers' levels
        effective_file_level = file_level if save_log else console_level # Consider file level only if saving
        logger.setLevel(min(console_level, effective_file_level))
        logger.propagate = False # Prevent logs from going to the root logger

        # --- Console Handler ---
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(PrettyFormatter())
        console_handler.setLevel(console_level) # Set console handler level
        logger.addHandler(console_handler)

        # --- File Handler (Optional) ---
        if save_log:
            try:
                # Ensure log directory exists
                os.makedirs(log_dir, exist_ok=True)
                log_file_path = os.path.join(log_dir, log_file)

                file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
                # Use a standard formatter for the file log
                file_formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S' # Standard date format
                )
                file_handler.setFormatter(file_formatter)
                file_handler.setLevel(file_level) # Set file handler level
                logger.addHandler(file_handler)
            except Exception as e:
                # Log error if file handler setup fails, but continue with console logging
                logger.error(f"Failed to set up file logging to {log_file_path}: {e}", exc_info=True)
                # Optionally, you could remove the failed handler if added partially,
                # but basic addHandler failures are less common than I/O errors later.


    # If logger was already configured, you could optionally update levels here,
    # but for simplicity, this setup assumes configuration happens once at startup.

    return logger

# --- Example Usage ---
if __name__ == "__main__":

    print("\n--- Scenario 1: Default Setup (Console=INFO, File=DEBUG) ---")
    # This is how you'd typically call it in your main script for normal operation
    logger1 = setup_logging(logger_name="App_Normal")
    logger1.debug("This is DEBUG - goes to file only.")
    logger1.info("This is INFO - goes to console and file.")
    logger1.warning("This is WARNING - goes to console and file.")

    # Clear handlers only for demonstration purposes in this example script
    logging.getLogger("App_Normal").handlers.clear()


    print("\n--- Scenario 2: Debugging Setup (Console=DEBUG, File=DEBUG) ---")
    # Call this way when you need detailed console output for debugging
    logger2 = setup_logging(logger_name="App_Debug", console_level=logging.DEBUG)
    logger2.debug("This is DEBUG - goes to console and file.")
    logger2.info("This is INFO - goes to console and file.")

    logging.getLogger("App_Debug").handlers.clear()


    print("\n--- Scenario 3: Console Only Setup (Console=WARNING) ---")
    # Example for console-only output, showing only WARNING and above
    logger3 = setup_logging(logger_name="App_ConsoleOnly", console_level=logging.WARNING, save_log=False)
    logger3.info("This is INFO - not shown.")
    logger3.warning("This is WARNING - shown on console only.")
    logger3.error("This is ERROR - shown on console only.")

    logging.getLogger("App_ConsoleOnly").handlers.clear()

    print("\n--- Scenario 4: Custom File Name ---")
    logger4 = setup_logging(logger_name="App_CustomFile", log_file="special_run.log")
    logger4.info("This INFO goes to console (INFO) and special_run.log (DEBUG).")

    logging.getLogger("App_CustomFile").handlers.clear()

    print("\nExample logging setup complete. Check 'Logs/General_Logs/' for log files.")