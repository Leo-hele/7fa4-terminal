//#define NDEBUG
#ifdef NDEBUG
#define print(...) (void)0
#else
#define print(...) void(fprintf(stderr, __VA_ARGS__))
#endif
#include<bits/extc++.h>
#define _fo(i, l, o, s, ...) for (auto i = l; o; i += (s))
#define fo(...) _fo(__VA_ARGS__, 1)
#define _up(i, l, r, s, ...) _fo(i, l, i <= r, s)
#define up(...) _up(__VA_ARGS__, 1)
#define _dn(i, l, r, s, ...) _fo(i, l, i >= r, -(s))
#define dn(...) _dn(__VA_ARGS__, 1)
using ll = long long;
using ull = unsigned long long;
using namespace std;
int main(){
    ios_base::sync_with_stdio(0), cin.tie(0), cout.tie(0);
    
    return 0;
}