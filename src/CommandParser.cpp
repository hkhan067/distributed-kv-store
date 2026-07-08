#include "CommandParser.h"

Command CommandParser::parse(const std::string &line) const
{
    std::stringstream ss(line); // stores line into ss

    std::string commandText = ""; 
    std::string key = "";
    std::string value = "";

    ss >> commandText; // takes the first word which is the command and stores it in commandText

    if (commandText == "PUT")
    {
        ss >> key; // ss is now on key and stores key string into string
        ss >> value; // ss is on value and stores value string into value

        if (value.empty() || key.empty())
        {
            return {CommandType::Invalid, "", ""};
        }
        return {CommandType::Put, key, value};
    }
    else if (commandText == "GET")
    {
        ss >> key;

        if (key.empty())
        {
            return {CommandType::Invalid, "", ""};
        }
        return {CommandType::Get, key, ""};
    }
    else if (commandText == "DELETE")
    {
        ss >> key;

        if (key.empty())
        {
            return {CommandType::Invalid, "", ""};
        }
        return {CommandType::Delete, key, ""};
    }   
    else if(commandText == "EXIT")
    {
        return {CommandType::Exit, "", ""};
    }
    
    return {CommandType::Invalid, "", ""};
}
