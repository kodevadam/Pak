/* globals_and_consts.c - global variables, static vars, constants */

#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240
#define MAX_ENTITIES 64
#define GRAVITY 9.8f
#define PI 3.14159f

static int frame_count = 0;
static float delta_time = 0.016f;
const int version = 1;

int entity_count = 0;

void tick(void) {
    frame_count++;
    delta_time = 1.0f / 60.0f;
}

int get_frame(void) {
    return frame_count;
}
