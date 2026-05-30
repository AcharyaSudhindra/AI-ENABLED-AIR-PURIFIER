#ifndef __AIR_PURIFIER_CONTROLLER_H__
#define __AIR_PURIFIER_CONTROLLER_H__

#include "mcp_server.h"
#include "board.h"

#include <esp_log.h>
#include <esp_http_client.h>
#include <cJSON.h>
#include <string>
#include <cstring>

#define TAG_AP "AirPurifier"

/**
 * AirPurifierController
 *
 * Registers MCP tools so the Xiaozhi AI assistant can control
 * a remote Air Purifier ESP32-S3 over the local WiFi network.
 *
 * The Air Purifier exposes:
 *   GET  /api/status  -> JSON with aqi, pm25, temperature, humidity, fan_on, mode, etc.
 *   POST /api/control -> JSON body with mode, fan_on, threshold_voltage
 *
 * This controller uses esp_http_client to talk to the purifier.
 */
class AirPurifierController {
private:
    std::string host_;   // e.g. "192.168.1.100" or "airpurifier.local"
    int port_;

    // ------- HTTP helpers -------

    // Perform GET and return response body (empty on error).
    std::string HttpGet(const std::string& path) {
        std::string url = "http://" + host_ + ":" + std::to_string(port_) + path;
        std::string result;

        esp_http_client_config_t config = {};
        config.url = url.c_str();
        config.timeout_ms = 4000;
        config.method = HTTP_METHOD_GET;

        esp_http_client_handle_t client = esp_http_client_init(&config);
        if (!client) {
            ESP_LOGE(TAG_AP, "Failed to init HTTP client");
            return result;
        }

        esp_err_t err = esp_http_client_open(client, 0);
        if (err != ESP_OK) {
            ESP_LOGE(TAG_AP, "GET open failed: %s", esp_err_to_name(err));
            esp_http_client_cleanup(client);
            return result;
        }

        int content_length = esp_http_client_fetch_headers(client);
        if (content_length < 0) content_length = 512;
        if (content_length > 2048) content_length = 2048;

        char* buf = (char*)malloc(content_length + 1);
        if (buf) {
            int read_len = esp_http_client_read(client, buf, content_length);
            if (read_len >= 0) {
                buf[read_len] = '\0';
                result = std::string(buf, read_len);
            }
            free(buf);
        }

        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return result;
    }

    // Perform POST with JSON body and return response body.
    std::string HttpPost(const std::string& path, const std::string& json_body) {
        std::string url = "http://" + host_ + ":" + std::to_string(port_) + path;
        std::string result;

        esp_http_client_config_t config = {};
        config.url = url.c_str();
        config.timeout_ms = 4000;
        config.method = HTTP_METHOD_POST;

        esp_http_client_handle_t client = esp_http_client_init(&config);
        if (!client) {
            ESP_LOGE(TAG_AP, "Failed to init HTTP client");
            return result;
        }

        esp_http_client_set_header(client, "Content-Type", "application/json");

        esp_err_t err = esp_http_client_open(client, json_body.size());
        if (err != ESP_OK) {
            ESP_LOGE(TAG_AP, "POST open failed: %s", esp_err_to_name(err));
            esp_http_client_cleanup(client);
            return result;
        }

        esp_http_client_write(client, json_body.c_str(), json_body.size());

        int content_length = esp_http_client_fetch_headers(client);
        if (content_length < 0) content_length = 512;
        if (content_length > 2048) content_length = 2048;

        char* buf = (char*)malloc(content_length + 1);
        if (buf) {
            int read_len = esp_http_client_read(client, buf, content_length);
            if (read_len >= 0) {
                buf[read_len] = '\0';
                result = std::string(buf, read_len);
            }
            free(buf);
        }

        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return result;
    }

public:
    AirPurifierController(const std::string& host, int port = 80)
        : host_(host), port_(port) {

        ESP_LOGI(TAG_AP, "Registering air purifier tools for %s:%d", host_.c_str(), port_);

        auto& mcp_server = McpServer::GetInstance();

        // ---- Tool 1: Get air purifier status ----
        mcp_server.AddTool(
            "self.air_purifier.get_status",
            "Get the current status of the air purifier including air quality index (AQI), "
            "PM2.5 dust level (ug/m3), temperature (Celsius), humidity (%), "
            "whether the fan is on, and the operating mode (auto/manual). "
            "Use this tool when the user asks about air quality, temperature, humidity, "
            "or the state of the air purifier.",
            PropertyList(),
            [this](const PropertyList& properties) -> ReturnValue {
                std::string response = HttpGet("/api/status");
                if (response.empty()) {
                    return std::string("{\"error\": \"Air purifier is not reachable. Check if it is powered on and connected to WiFi.\"}");
                }
                // Parse and format a human-friendly summary
                cJSON* json = cJSON_Parse(response.c_str());
                if (!json) {
                    return std::string("{\"error\": \"Invalid response from air purifier\"}");
                }

                cJSON* aqi = cJSON_GetObjectItem(json, "aqi");
                cJSON* pm25 = cJSON_GetObjectItem(json, "pm25");
                cJSON* temp = cJSON_GetObjectItem(json, "temperature_c");
                cJSON* hum = cJSON_GetObjectItem(json, "humidity");
                cJSON* fan = cJSON_GetObjectItem(json, "fan_on");
                cJSON* mode = cJSON_GetObjectItem(json, "mode");
                cJSON* uptime = cJSON_GetObjectItem(json, "uptime_sec");

                cJSON* result = cJSON_CreateObject();
                if (aqi) cJSON_AddNumberToObject(result, "aqi", aqi->valuedouble);
                if (pm25) cJSON_AddNumberToObject(result, "pm25_ug_m3", pm25->valuedouble);
                if (temp) cJSON_AddNumberToObject(result, "temperature_celsius", temp->valuedouble);
                if (hum) cJSON_AddNumberToObject(result, "humidity_percent", hum->valuedouble);
                if (fan) cJSON_AddBoolToObject(result, "fan_is_on", cJSON_IsTrue(fan));
                if (mode) cJSON_AddStringToObject(result, "mode", mode->valuestring);
                if (uptime) cJSON_AddNumberToObject(result, "uptime_seconds", uptime->valuedouble);

                // Add air quality description
                if (aqi) {
                    int aqi_val = (int)aqi->valuedouble;
                    const char* desc = "Unknown";
                    if (aqi_val <= 50) desc = "Good";
                    else if (aqi_val <= 100) desc = "Moderate";
                    else if (aqi_val <= 150) desc = "Unhealthy for Sensitive Groups";
                    else if (aqi_val <= 200) desc = "Unhealthy";
                    else if (aqi_val <= 300) desc = "Very Unhealthy";
                    else desc = "Hazardous";
                    cJSON_AddStringToObject(result, "air_quality_description", desc);
                }

                cJSON_Delete(json);
                // Return the cJSON object; McpServer will serialize it
                return result;
            });

        // ---- Tool 2: Turn on air purifier ----
        mcp_server.AddTool(
            "self.air_purifier.turn_on",
            "Turn ON the air purifier fan. This switches the purifier to manual mode "
            "and activates the fan immediately. Use when the user says things like "
            "'turn on the air purifier', 'start the fan', 'activate the purifier'.",
            PropertyList(),
            [this](const PropertyList& properties) -> ReturnValue {
                std::string body = "{\"mode\":\"manual\",\"fan_on\":true}";
                std::string response = HttpPost("/api/control", body);
                if (response.empty()) {
                    return std::string("Failed to reach the air purifier. Is it powered on?");
                }
                return std::string("Air purifier fan is now ON (manual mode).");
            });

        // ---- Tool 3: Turn off air purifier ----
        mcp_server.AddTool(
            "self.air_purifier.turn_off",
            "Turn OFF the air purifier fan. This switches the purifier to manual mode "
            "and deactivates the fan immediately. Use when the user says things like "
            "'turn off the air purifier', 'stop the fan', 'deactivate the purifier'.",
            PropertyList(),
            [this](const PropertyList& properties) -> ReturnValue {
                std::string body = "{\"mode\":\"manual\",\"fan_on\":false}";
                std::string response = HttpPost("/api/control", body);
                if (response.empty()) {
                    return std::string("Failed to reach the air purifier. Is it powered on?");
                }
                return std::string("Air purifier fan is now OFF (manual mode).");
            });

        // ---- Tool 4: Set auto mode ----
        mcp_server.AddTool(
            "self.air_purifier.set_auto_mode",
            "Set the air purifier to automatic mode. In auto mode, the fan turns on/off "
            "automatically based on the air quality index (AQI) threshold. "
            "Use when the user says 'set to auto', 'automatic mode', 'let it decide'.",
            PropertyList(),
            [this](const PropertyList& properties) -> ReturnValue {
                std::string body = "{\"mode\":\"auto\"}";
                std::string response = HttpPost("/api/control", body);
                if (response.empty()) {
                    return std::string("Failed to reach the air purifier. Is it powered on?");
                }
                return std::string("Air purifier is now in automatic mode. The fan will turn on/off based on air quality.");
            });

        // ---- Tool 5: Set AQI threshold ----
        mcp_server.AddTool(
            "self.air_purifier.set_threshold",
            "Set the AQI threshold for automatic fan control. When AQI reaches this value, "
            "the fan turns on automatically. Valid range: 50-400. Default is 175. "
            "Use when the user says 'set threshold to 150' or 'make it more sensitive'.",
            PropertyList({
                Property("aqi_threshold", kPropertyTypeInteger, 50, 400)
            }),
            [this](const PropertyList& properties) -> ReturnValue {
                int threshold = properties["aqi_threshold"].value<int>();
                // Convert AQI threshold to voltage: voltage = (aqi / 500.0) * 3.3
                float voltage = (threshold / 500.0f) * 3.3f;

                std::string body = "{\"mode\":\"auto\",\"threshold_voltage\":" + 
                    std::to_string(voltage) + "}";
                std::string response = HttpPost("/api/control", body);
                if (response.empty()) {
                    return std::string("Failed to reach the air purifier. Is it powered on?");
                }
                return std::string("AQI threshold set to " + std::to_string(threshold) + 
                    ". Fan will activate when AQI reaches this level.");
            });

        // ---- Tool 6: Set purifier IP address ----
        mcp_server.AddTool(
            "self.air_purifier.set_ip",
            "Set the IP address or hostname of the air purifier. "
            "Default is 'airpurifier.local'. Use this if the purifier has a different IP. "
            "Example: '192.168.1.105' or 'airpurifier.local'.",
            PropertyList({
                Property("ip_address", kPropertyTypeString)
            }),
            [this](const PropertyList& properties) -> ReturnValue {
                host_ = properties["ip_address"].value<std::string>();
                ESP_LOGI(TAG_AP, "Air purifier address updated to: %s", host_.c_str());
                return std::string("Air purifier address set to: " + host_);
            });
    }
};

#endif // __AIR_PURIFIER_CONTROLLER_H__
