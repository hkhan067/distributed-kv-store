#include "CommandParser.h"
#include "KeyValueStore.h"
#include "PersistenceLog.h"

#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace
{
const std::string logPath = "level5_test.log";

void expect(bool condition, const std::string &message)
{
    if (!condition)
    {
        std::cerr << "FAILED: " << message << std::endl;
        std::exit(1);
    }
}

void cleanTestFiles()
{
    std::remove(logPath.c_str());
    std::remove((logPath + ".tmp").c_str());
    rmdir((logPath + ".tmp").c_str());
}

std::size_t countLines(const std::string &path)
{
    std::ifstream file(path);
    std::size_t lineCount = 0;
    std::string line;

    while (std::getline(file, line))
    {
        lineCount++;
    }

    return lineCount;
}

void expectValue(
    const KeyValueStore &store,
    const std::string &key,
    const std::string &expectedValue
)
{
    std::string value;
    expect(store.get(key, value), "expected key " + key);
    expect(value == expectedValue, "unexpected value for key " + key);
}

void testCompactCommand()
{
    CommandParser parser;
    Command command = parser.parse("COMPACT");
    expect(command.type == CommandType::Compact, "COMPACT should be valid");
}

void testCompactionAndRecovery()
{
    cleanTestFiles();

    KeyValueStore store;
    PersistenceLog log(logPath);

    expect(log.appendPut("alpha", "one"), "first PUT should be logged");
    store.put("alpha", "one");

    expect(log.appendPut("alpha", "two"), "updated PUT should be logged");
    store.put("alpha", "two");

    expect(log.appendPut("beta", "value"), "beta PUT should be logged");
    store.put("beta", "value");

    expect(log.appendDelete("beta"), "DELETE should be logged");
    expect(store.remove("beta"), "beta should be removed");

    expect(log.appendPut("gamma", "three"), "gamma PUT should be logged");
    store.put("gamma", "three");

    expect(countLines(logPath) == 5, "original log should contain five records");
    expect(log.compact(store.snapshot()), "compaction should succeed");
    expect(countLines(logPath) == 2, "compacted log should contain two live keys");

    KeyValueStore recoveredStore;
    log.load(recoveredStore);

    expectValue(recoveredStore, "alpha", "two");
    expectValue(recoveredStore, "gamma", "three");

    std::string value;
    expect(!recoveredStore.get("beta", value), "deleted beta should not recover");

    expect(log.appendPut("delta", "four"), "writes after compaction should work");
    recoveredStore.put("delta", "four");

    KeyValueStore recoveredAgain;
    log.load(recoveredAgain);
    expectValue(recoveredAgain, "alpha", "two");
    expectValue(recoveredAgain, "gamma", "three");
    expectValue(recoveredAgain, "delta", "four");
}

void testEmptyCompaction()
{
    cleanTestFiles();

    KeyValueStore emptyStore;
    PersistenceLog log(logPath);

    expect(log.appendPut("old", "value"), "setup PUT should be logged");
    expect(log.compact(emptyStore.snapshot()), "empty compaction should succeed");
    expect(countLines(logPath) == 0, "empty store should produce an empty log");

    KeyValueStore recoveredStore;
    log.load(recoveredStore);

    std::string value;
    expect(!recoveredStore.get("old", value), "old key should not recover");
}

void testMalformedRecordsAreIgnored()
{
    cleanTestFiles();

    std::ofstream file(logPath, std::ios::trunc);
    file << "PUT valid value\n";
    file << "PUT incomplete\n";
    file << "DELETE\n";
    file.close();

    PersistenceLog log(logPath);
    KeyValueStore recoveredStore;
    log.load(recoveredStore);

    expectValue(recoveredStore, "valid", "value");

    std::string value;
    expect(!recoveredStore.get("incomplete", value), "incomplete PUT should be ignored");
}

void testFailuresKeepTheOriginalLog()
{
    cleanTestFiles();

    PersistenceLog log(logPath);
    expect(log.appendPut("safe", "value"), "setup PUT should be logged");

    expect(mkdir((logPath + ".tmp").c_str(), 0700) == 0, "temporary directory setup");

    KeyValueStore store;
    store.put("replacement", "value");
    expect(!log.compact(store.snapshot()), "compaction should report a temp-file failure");

    KeyValueStore recoveredStore;
    log.load(recoveredStore);
    expectValue(recoveredStore, "safe", "value");

    std::string value;
    expect(!recoveredStore.get("replacement", value), "failed compaction must keep old log");

    rmdir((logPath + ".tmp").c_str());

    PersistenceLog invalidLog("missing_level5_directory/kv.log");
    expect(!invalidLog.appendPut("key", "value"), "invalid append path should fail");
    expect(!invalidLog.compact(store.snapshot()), "invalid compact path should fail");
}
}

int main()
{
    testCompactCommand();
    testCompactionAndRecovery();
    testEmptyCompaction();
    testMalformedRecordsAreIgnored();
    testFailuresKeepTheOriginalLog();

    cleanTestFiles();

    std::cout << "Level 5 tests passed." << std::endl;
    return 0;
}
