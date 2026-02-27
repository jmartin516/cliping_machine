/*
 * CustosAI Clipper — Pty launcher for macOS
 *
 * Gives the real binary a pseudo-TTY so Tk doesn't crash (NSCalendarDate).
 * Uses openpty + dup2 + exec — NO fork. Same process becomes the app.
 * Single process = single Dock icon.
 */
#include <stdlib.h>
#include <unistd.h>
#include <util.h>   /* openpty on macOS */

int main(int argc, char *argv[]) {
    if (argc < 2) return 1;
    int master, slave;
    if (openpty(&master, &slave, NULL, NULL, NULL) != 0) return 1;
    dup2(slave, 0);
    dup2(slave, 1);
    dup2(slave, 2);
    if (slave > 2) close(slave);
    close(master);
    execv(argv[1], argv + 1);
    _exit(127);
}
