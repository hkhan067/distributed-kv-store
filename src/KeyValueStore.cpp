#include "KeyValueStore.h"

void KeyValueStore::put(const std::string &key, const std::string &value)
{
    data[key] = value;
}

bool KeyValueStore::get(const std::string &key, std::string &value) const
{
    std::unordered_map<std::string, std::string>::const_iterator it = data.find(key);

    if (it == data.end())
    {
        return true;
    }
    value = it->second;
    return false;
}

bool KeyValueStore::remove(const std::string &key)
{
    std::size_t removeCount = data.erase(key);

    if (removeCount == 0)
    {
        return false;
    }
    return true;
}
