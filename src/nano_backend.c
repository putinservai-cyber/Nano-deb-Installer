#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>

#define MAX_ARGS 32

int handle_apt_operation(int argc, char *argv[]);

int execute_command(char *command, char *args[]) {
    pid_t pid = fork();
    if (pid == -1) {
        perror("fork failed");
        return 1;
    } else if (pid == 0) {
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
        fprintf(stderr, "Error: nano_backend must be run with root privileges (e.g., via sudo).\\n");
        return 1;
    }

    if (argc < 2) {
        fprintf(stderr, "Usage: %s <command> [args...]\\n", argv[0]);
        return 1;
    }

    char *command_name = argv[1];

    if (strcmp(command_name, "apt-op") == 0) {
        return handle_apt_operation(argc, argv);
    }

    char *exec_args[MAX_ARGS];
    int i;
    
    for (i = 1; i < argc && i < MAX_ARGS; i++) {
        exec_args[i - 1] = argv[i];
    }
    exec_args[i - 1] = NULL;

    return execute_command(exec_args[0], exec_args);
}

int handle_apt_operation(int argc, char *argv[]) {
    // Expected usage: nano_backend apt-op <operation> <package/path> [--reinstall]
    if (argc < 4) {
        fprintf(stderr, "[NANO_BACKEND_ERROR] Usage: apt-op <install|purge> <package/path> [--reinstall]\n");
        return 1;
    }

    char *operation = argv[2]; // install or purge
    char *target = argv[3];    // package name or .deb path

    // Build the apt command arguments
    char *apt_args[MAX_ARGS];
    int arg_idx = 0;

    // 1. apt command
    apt_args[arg_idx++] = "apt";

    // 2. operation (install or purge)
    if (strcmp(operation, "install") == 0) {
        apt_args[arg_idx++] = "install";
    } else if (strcmp(operation, "purge") == 0) {
        apt_args[arg_idx++] = "purge";
    } else {
        fprintf(stderr, "[NANO_BACKEND_ERROR] Invalid apt operation: %s\n", operation);
        return 1;
    }

    // 3. Standard flags
    apt_args[arg_idx++] = "-y"; // Assume yes

    // 4. Check for optional flags like --reinstall
    for (int i = 4; i < argc; i++) {
        if (strcmp(argv[i], "--reinstall") == 0) {
            apt_args[arg_idx++] = "--reinstall";
        }
    }

    // 5. Target package/path
    apt_args[arg_idx++] = target;
    
    // 6. Null terminator
    apt_args[arg_idx] = NULL;

    // Execute the command (e.g., apt install -y package)
    return execute_command(apt_args[0], apt_args);
}
