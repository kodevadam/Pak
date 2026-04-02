/* goto_defer.c - goto cleanup pattern */

int load_data(const char *path, int *out) {
    char *buf = (char*)0;
    int result = 0;
    buf = (char*)0;
    if (!buf) goto cleanup_buf;
    *out = 42;
    result = 1;
cleanup_buf:
    buf = (char*)0;
    return result;
}
