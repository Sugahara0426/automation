#!/usr/local/bin/python3

#==========================================================
# An NRP2 LAN Controller Module
#  by Using a VXI11 Module
#
# Coded by S. Nishimura 2022/02/18 ver0.1
#==========================================================

import string
import time
import sys
import vxi11

class RaS_NRP2:
    """ NRP2 controller class with VXI11 """

    __IP_ADDRESS__ = str()  # IP address of SMB 100A
    __WAIT_TIME__  = 0.1       # wating time after sending command (sec)

    #----------------------------
    # Construnter 
    #----------------------------
    def __init__( self, ip_address ):
        self.__IP_ADDRESS__ = ip_address

        # Open the device
        print("Connecting to NRP2 @ " + self.__IP_ADDRESS__ + " ....  ")
        self.ras_nrp2 = vxi11.Instrument( self.__IP_ADDRESS__ )
    
        # Initialize and config.
        #        print( "Connecting SMB 100A ....  ")
        #        self.Reset()
        #        self.Write("TRIG:SOUR BUS") # set trigger mode for GPIB/LAN/USB
        #        self.Write(":CORR:LENG 1")  # cable length correction @ 1 m
        #        self.Write(":CORR:SHOR:STAT ON;:CORR:OPEN:STAT ON") # Open/Short Correction ON
        #        self.SetVAC("1") # Set Vac at 1 V
        #print ("Finitshed.\n")
        
    #----------------------------------------------
    # Send Command to the NRP2
    #----------------------------------------------
    def Write( self, command ):
        self.ras_nrp2.write( command )
        time.sleep( self.__WAIT_TIME__ )

    #------------------------------------
    # Reset ( Not recommended )
    #-----------------------------------
    def Reset( self ):
        self.Write("*RST;*CLS")

    #------------------------------
    # Read Power
    #------------------------------
    def GetPower( self, channel = 1 ):
        command = ":FETC" + str( channel ) + "?"
        _pow = self.ras_nrp2.ask( command )
        return float( _pow )

