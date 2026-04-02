/* fixed_point.c - fixed-point arithmetic */
typedef int fix16;
#define FIX16_ONE 65536

fix16 velocity = 5 * 65536;
fix16 friction = 62259;

fix16 update_vel(fix16 v, fix16 f) {
    return (int)(((long long)v * f) >> 16);
}
