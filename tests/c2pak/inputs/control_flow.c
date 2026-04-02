/* control_flow.c - Phase 2 milestone test: expressions and statements */

int gcd(int a, int b) {
    while (b != 0) {
        int temp = b;
        b = a % b;
        a = temp;
    }
    return a;
}

void bubble_sort(int *arr, int n) {
    for (int i = 0; i < n - 1; i++) {
        for (int j = 0; j < n - i - 1; j++) {
            if (arr[j] > arr[j + 1]) {
                int tmp = arr[j];
                arr[j] = arr[j + 1];
                arr[j + 1] = tmp;
            }
        }
    }
}

int abs_val(int x) {
    return x < 0 ? -x : x;
}

int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}

void count_down(int n) {
    while (n > 0) {
        n--;
    }
}

int sum_array(int *data, int count) {
    int total = 0;
    for (int i = 0; i < count; i++) {
        total += data[i];
    }
    return total;
}

void direction_test(int dir) {
    switch (dir) {
        case 0: break;
        case 1: break;
        case 2: break;
        default: break;
    }
}
