// Component-extraction shim.
//
// Upstream steam-audio defines gLog()/gMemory() in core/src/core/context.cpp,
// which pulls in the whole context / HRTF / scene subsystem.  The FFT component
// only needs the global allocator and logger, so this file provides the same
// definitions with the same linkage.  Nothing else about the component changes.
#include "log.h"
#include "memory_allocator.h"

namespace ipl {

namespace {

Memory sMemory;
Log sLog;

}

Log& gLog()
{
    return sLog;
}

Memory& gMemory()
{
    return sMemory;
}

}