/* Isolated network-lifecycle fixture, never shipped in production packages. */
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
static volatile sig_atomic_t running = 1;
static void stop(int sig) { (void)sig; running = 0; }
static int request(const char *action, const char *name) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    struct sockaddr_un addr = { .sun_family = AF_UNIX };
    strcpy(addr.sun_path, "/lab/control.sock");
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) return 1;
    char msg[256];
    int n = snprintf(msg, sizeof(msg), "%s %s\n", action, name);
    if (write(fd, msg, n) != n) { close(fd); return 1; }
    memset(msg, 0, sizeof(msg));
    n = read(fd, msg, sizeof(msg)-1);
    close(fd);
    return n < 2 || strncmp(msg, "OK", 2) != 0;
}
int main(int argc, char **argv) {
    if (argc > 1 && !strcmp(argv[1], "--version")) { puts("router-lifecycle-fixture 1"); return 0; }
    char name[128] = {0};
    gethostname(name, sizeof(name)-1);
    signal(SIGTERM, stop); signal(SIGINT, stop); signal(SIGHUP, stop);
    if (request("start", name)) return 1;
    while (running) pause();
    return request("stop", name);
}
