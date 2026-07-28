#include <arpa/inet.h>
#include <errno.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define BUFFER_SIZE 16384

static const char *mime_type(const char *path) {
    const char *extension = strrchr(path, '.');
    if (extension == NULL) return "application/octet-stream";
    if (strcmp(extension, ".html") == 0) return "text/html; charset=utf-8";
    if (strcmp(extension, ".css") == 0) return "text/css; charset=utf-8";
    if (strcmp(extension, ".js") == 0) return "text/javascript; charset=utf-8";
    if (strcmp(extension, ".json") == 0) return "application/json; charset=utf-8";
    if (strcmp(extension, ".jpg") == 0 || strcmp(extension, ".jpeg") == 0) return "image/jpeg";
    if (strcmp(extension, ".png") == 0) return "image/png";
    if (strcmp(extension, ".txt") == 0) return "text/plain; charset=utf-8";
    return "application/octet-stream";
}

static void send_text(int client, int status, const char *message) {
    char header[512];
    int length = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 %d\r\nContent-Type: text/plain; charset=utf-8\r\n"
        "Content-Length: %zu\r\nConnection: close\r\nCache-Control: no-store\r\n\r\n",
        status,
        strlen(message)
    );
    send(client, header, (size_t)length, 0);
    send(client, message, strlen(message), 0);
}

static void serve_file(int client, const char *request_path) {
    char path[4096];
    const char *relative = request_path;
    if (strcmp(relative, "/") == 0) relative = "/index.html";
    if (strstr(relative, "..") != NULL || strchr(relative, '\\') != NULL) {
        send_text(client, 403, "拒绝访问");
        return;
    }
    const char *query = strchr(relative, '?');
    size_t path_length = query == NULL ? strlen(relative) : (size_t)(query - relative);
    if (path_length + 2 > sizeof(path)) {
        send_text(client, 414, "地址过长");
        return;
    }
    path[0] = '.';
    memcpy(path + 1, relative, path_length);
    path[path_length + 1] = '\0';

    struct stat details;
    if (stat(path, &details) != 0 || !S_ISREG(details.st_mode)) {
        send_text(client, 404, "未找到文件");
        return;
    }
    FILE *file = fopen(path, "rb");
    if (file == NULL) {
        send_text(client, 500, "无法读取文件");
        return;
    }
    char header[1024];
    int header_length = snprintf(
        header,
        sizeof(header),
        "HTTP/1.1 200 OK\r\nContent-Type: %s\r\nContent-Length: %lld\r\n"
        "Connection: close\r\nCache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n\r\n",
        mime_type(path),
        (long long)details.st_size
    );
    send(client, header, (size_t)header_length, 0);
    char buffer[BUFFER_SIZE];
    size_t count;
    while ((count = fread(buffer, 1, sizeof(buffer), file)) > 0) {
        if (send(client, buffer, count, 0) < 0) break;
    }
    fclose(file);
}

static void print_addresses(unsigned short port) {
    printf("\n离线效果展厅已经启动。\n");
    printf("本机地址：http://127.0.0.1:%u/\n", port);
    printf("手机和平板需连接同一 Wi-Fi，然后访问：\n");
    struct ifaddrs *addresses = NULL;
    if (getifaddrs(&addresses) == 0) {
        for (struct ifaddrs *item = addresses; item != NULL; item = item->ifa_next) {
            if (item->ifa_addr == NULL || item->ifa_addr->sa_family != AF_INET) continue;
            if ((item->ifa_flags & IFF_LOOPBACK) != 0) continue;
            char address[INET_ADDRSTRLEN];
            struct sockaddr_in *value = (struct sockaddr_in *)item->ifa_addr;
            if (inet_ntop(AF_INET, &value->sin_addr, address, sizeof(address)) != NULL) {
                printf("  http://%s:%u/\n", address, port);
            }
        }
        freeifaddrs(addresses);
    }
    printf("\n保持此窗口开启即可浏览；按 Control + C 结束。\n\n");
    fflush(stdout);
}

static void open_browser(unsigned short port) {
    pid_t child = fork();
    if (child != 0) return;
    char url[128];
    snprintf(url, sizeof(url), "http://127.0.0.1:%u/", port);
#if defined(__APPLE__)
    execlp("open", "open", url, (char *)NULL);
#else
    execlp("xdg-open", "xdg-open", url, (char *)NULL);
#endif
    _exit(0);
}

int main(void) {
    signal(SIGPIPE, SIG_IGN);
    int server = socket(AF_INET, SOCK_STREAM, 0);
    if (server < 0) {
        perror("无法创建服务");
        return 1;
    }
    int reuse = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &reuse, sizeof(reuse));

    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    address.sin_port = htons(4175);
    if (bind(server, (struct sockaddr *)&address, sizeof(address)) != 0) {
        address.sin_port = 0;
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) != 0) {
            perror("无法绑定端口");
            close(server);
            return 1;
        }
    }
    if (listen(server, 32) != 0) {
        perror("无法启动服务");
        close(server);
        return 1;
    }
    socklen_t address_size = sizeof(address);
    if (getsockname(server, (struct sockaddr *)&address, &address_size) != 0) {
        perror("无法读取端口");
        close(server);
        return 1;
    }
    unsigned short port = ntohs(address.sin_port);
    print_addresses(port);
    open_browser(port);

    for (;;) {
        int client = accept(server, NULL, NULL);
        if (client < 0) {
            if (errno == EINTR) continue;
            perror("连接失败");
            break;
        }
        char request[BUFFER_SIZE];
        ssize_t count = recv(client, request, sizeof(request) - 1, 0);
        if (count <= 0) {
            close(client);
            continue;
        }
        request[count] = '\0';
        char method[16];
        char path[4096];
        if (sscanf(request, "%15s %4095s", method, path) != 2 || strcmp(method, "GET") != 0) {
            send_text(client, 405, "只支持读取");
        } else {
            serve_file(client, path);
        }
        close(client);
    }
    close(server);
    return 0;
}
