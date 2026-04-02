/* n64_homebrew.c - libdragon-style N64 homebrew program */
#include <libdragon.h>

int main(void) {
    display_init(RESOLUTION_320x240, DEPTH_16_BPP, 3, GAMMA_NONE, FILTERS_RESAMPLE);
    rdpq_init();
    while(1) {
        joypad_poll();
        surface_t *disp = display_get();
        rdpq_attach_clear(disp, NULL);
        rdpq_detach_show();
    }
}
