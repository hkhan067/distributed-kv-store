#pragma once

#include <unordered_map>
#include <string>

class KeyValueStore
{
private:
    std::unordered_map<std::string, std::string> data;

public:
    void put(const std::string &key, const std::string &value);
    bool get(const std::string &key, std::string &value) const;
    bool remove(const std::string &key);
};