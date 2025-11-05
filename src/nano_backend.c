#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <ctype.h>
#include <limits.h> // For PATH_MAX

#define MAX_ARGS 32
#define ERROR_PREFIX "[NANO_BACKEND_ERROR] "

int handle_apt_operation(int argc, char *argv[]);
int is_valid_package_name(const char *name);
int is_valid_deb_path(const char *path);

int execute_command(char *command, char *args[]) {
    pid_t pid = fork();
    if (pid == -1) {
        perror("fork failed");
        return 1;
    } else if (pid == 0) {
        // Set DEBIAN_FRONTEND to noninteractive to prevent apt/dpkg from prompting
        setenv("DEBIAN_FRONTEND", "noninteractive", 1);
        execvp(command, args);
        perror("execvp failed");
        _exit(1);
    } else {
        int status;
        if (waitpid(pid, &status, 0) == -1) {
            perror("waitpid failed");
            return 1;
        }
        if (WIFEXITED(status)) {
            return WEXITSTATUS(status);
        } else {
            return 1;
        }
    }
}

int main(int argc, char *argv[]) {
    if (geteuid() != 0) {
        fprintf(stderr, ERROR_PREFIX "This helper must be run with root privileges.\n");
        return 1;
    }

    if (argc < 2) {
        fprintf(stderr, ERROR_PREFIX "Usage: %s <command> [args...]\n", argv[0]);
        return 1;
    }

    char *command_name = argv[1];

    if (strcmp(command_name, "apt-op") == 0) {
        return handle_apt_operation(argc, argv);
    } else if (strcmp(command_name, "apt-autoremove") == 0) {
        return handle_apt_operation(argc, argv);
    } else if (strcmp(command_name, "apt-update") == 0) {
        return handle_apt_operation(argc, argv);
    } else if (strcmp(command_name, "apt-upgrade") == 0) {
        return handle_apt_operation(argc, argv);
    } else if (strcmp(command_name, "apt-fix-broken") == 0) {
        return handle_apt_operation(argc, argv);
    } else if (strcmp(command_name, "apt-clean") == 0) {
        return handle_apt_operation(argc, argv);
    }

    fprintf(stderr, ERROR_PREFIX "Unknown command: %s\n", command_name);
    return 1;
}

int handle_apt_operation(int argc, char *argv[]) {
    // This function now handles multiple command types passed from main().
    // argv[1] is the command that got us here.
    char *command_type = argv[1];

    // Validate argument count based on command type
    if (strcmp(command_type, "apt-op") == 0) {
        if (argc < 4) {
            fprintf(stderr, ERROR_PREFIX "Usage: %s <install|purge> <target> [--reinstall]\n", command_type);
            return 1;
        }
    } else if (argc != 2) {
        // All other commands (apt-autoremove, apt-update, etc.) should only have 2 arguments:
        // argv[0] = path/to/nano_backend, argv[1] = command_type
        fprintf(stderr, ERROR_PREFIX "Usage: %s %s\n", argv[0], command_type);
        return 1;
    }

    char *operation = NULL;
    char *target = NULL;

    if (strcmp(command_type, "apt-op") == 0) {
        operation = argv[2]; // install or purge
        target = argv[3];    // package name or .deb path
    }

    // Build the apt command arguments
    char *apt_args[MAX_ARGS];
    int arg_idx = 0;

    // 1. apt command
    apt_args[arg_idx++] = "/usr/bin/apt";

    if (strcmp(command_type, "apt-op") == 0) {
        // 2. operation (install or purge)
        if (strcmp(operation, "install") == 0) {
            // For install, the target must be a valid and safe .deb file path.
            if (!is_valid_deb_path(target)) {
                fprintf(stderr, ERROR_PREFIX "Invalid or unsafe .deb file path provided for install: %s\n", target);
                return 1;
            }
            apt_args[arg_idx++] = "install";
        } else if (strcmp(operation, "purge") == 0) {
            // For purge, the target must be a valid package name.
            if (!is_valid_package_name(target)) {
                fprintf(stderr, ERROR_PREFIX "Invalid package name provided for purge: %s\n", target);
                return 1;
            }
            apt_args[arg_idx++] = "purge";
        } else {
            fprintf(stderr, ERROR_PREFIX "Invalid apt operation: %s\n", operation);
            return 1;
        }
    } else if (strcmp(command_type, "apt-autoremove") == 0) {
        apt_args[arg_idx++] = "autoremove";
    } else if (strcmp(command_type, "apt-update") == 0) {
        apt_args[arg_idx++] = "update";
    } else if (strcmp(command_type, "apt-upgrade") == 0) {
        apt_args[arg_idx++] = "upgrade";
    } else if (strcmp(command_type, "apt-fix-broken") == 0) {
        // This handles 'apt --fix-broken install'
        apt_args[arg_idx++] = "--fix-broken";
        apt_args[arg_idx++] = "install";
    } else if (strcmp(command_type, "apt-clean") == 0) {
        apt_args[arg_idx++] = "clean";
    } else { // Should not be reached if main() is correct
        fprintf(stderr, ERROR_PREFIX "Unknown command type routed to apt handler: %s\n", command_type);
        return 1;
    }

    // 3. Standard flags (only for operations that need it)
    if (strcmp(command_type, "apt-op") == 0 || strcmp(command_type, "apt-autoremove") == 0 || strcmp(command_type, "apt-upgrade") == 0 || strcmp(command_type, "apt-fix-broken") == 0) {
        apt_args[arg_idx++] = "-y"; // Assume yes
    }

    // 4. Check for optional flags like --reinstall
    if (strcmp(command_type, "apt-op") == 0) {
        for (int i = 4; i < argc; i++) {
            if (strcmp(argv[i], "--reinstall") == 0) {
                apt_args[arg_idx++] = "--reinstall";
            }
        }

        // 5. Target package/path
        apt_args[arg_idx++] = target;
    }
    
    // 6. Null terminator
    apt_args[arg_idx] = NULL;

    // Execute the command (e.g., apt install -y package)
    return execute_command(apt_args[0], apt_args);
}

/**
 * Validates that a string is a safe package name.
 * Allows: a-z, 0-9, +, -, .
 * Must not start with a hyphen.
 */
int is_valid_package_name(const char *name) {
    if (name == NULL || name[0] == '\0' || name[0] == '-') {
        return 0; // Empty, null, or starts with a hyphen (could be an option)
    }
    for (int i = 0; name[i] != '\0'; i++) {
        if (!isalnum(name[i]) && name[i] != '+' && name[i] != '-' && name[i] != '.') {
            return 0; // Invalid character found
        }
    }
    return 1;
}

/**
 * Validates that a string is a safe, absolute path to a .deb file.
 * Prevents path traversal and ensures it ends with .deb.
 */
int is_valid_deb_path(const char *path) {
    if (path == NULL || path[0] != '/') {
        return 0; // Not an absolute path
    }

    size_t len = strlen(path);
    if (len < 5 || strcmp(path + len - 4, ".deb") != 0) {
        return 0; // Does not end with .deb
    }

    // Check for path traversal sequences like "/../" or "//"
    if (strstr(path, "/../") != NULL || strstr(path, "//") != NULL) {
        return 0;
    }

    // Check for invalid characters in the path
    for (int i = 0; path[i] != '\0'; i++) {
        // Allow alphanum, /, -, _, ., +, and space (unquoted from file:// URI)
        if (!isalnum(path[i]) && path[i] != '/' && path[i] != '-' && path[i] != '_' && path[i] != '.' && path[i] != '+' && path[i] != ' ') {
            return 0;
        }
    }

    return 1;
}
