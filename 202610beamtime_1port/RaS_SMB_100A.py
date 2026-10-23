#!/usr/local/bin/python3

#==========================================================
# An SMB 100A LAN Controller Module
#  by Using a VXI11 Module
#
# Coded by S. Nishimura 2022/02/18 ver0.1
#==========================================================

import string
import time
import sys
import vxi11

class RaS_SMB_100A:
    """ SMB 100A controller class with VXI11 """

    __IP_ADDRESS__ = str()  # IP address of SMB 100A
    __WAIT_TIME__  = 0.1       # wating time after sending command (sec)

    #----------------------------
    # Construnter 
    #----------------------------
    def __init__( self, ip_address ):
        self.__IP_ADDRESS__ = ip_address

        # Open the device
        print("Connecting to SMB 100A @ " + self.__IP_ADDRESS__ + " ....  ")
        self.ras_smb_100a = vxi11.Instrument( self.__IP_ADDRESS__ )
    
        # Initialize and config.
        #        print( "Connecting SMB 100A ....  ")
        #        self.Reset()
        #        self.Write("TRIG:SOUR BUS") # set trigger mode for GPIB/LAN/USB
        #        self.Write(":CORR:LENG 1")  # cable length correction @ 1 m
        #        self.Write(":CORR:SHOR:STAT ON;:CORR:OPEN:STAT ON") # Open/Short Correction ON
        #        self.SetVAC("1") # Set Vac at 1 V
        #print ("Finitshed.\n")
        
    #----------------------------------------------
    # Send Command to the SMB 100A
    #----------------------------------------------
    def Write( self, command ):
        self.ras_smb_100a.write( command )
        time.sleep( self.__WAIT_TIME__ )

    #------------------------------------
    # Reset ( Not recommended )
    #-----------------------------------
    def Reset( self ):
        self.Write("*RST;*CLS")


    #-----------------------------
    # Set Microwave Frequency
    #-----------------------------
    def SetFrequency( self, _freq ):
        self.Write( ":FREQ " + str( _freq ))

    #-----------------------------
    # Set Microwave Power
    #-----------------------------
    def SetPower( self, _amp ):
        self.Write( ":POW " + str( _amp ))

    #------------------------------
    # Set Microwave I/O
    #------------------------------
    def SetIO( self, _status ):
        self.Write( ":OUTP " + str( _status ) ) 

        
    #-------------------------------
    # Set Blind Mode (Annotation)
    #     0 : Blind mode
    #     1 : Unblind mode
    #-------------------------------
    def SetBlindMode( self, _mode ):
        self.Write( ":DISP:ANN:FREQ " + str( _mode ) ) 

    #------------------------------------------------------------------------------------
    # Set Modulation Mode
    #    Input the pulse signal whose voltage is between 1.5 V and < 5 V from Pulse EXT
    #    when you use pulse modulation
    #------------------------------------------------------------------------------------
    def SetModulation( self, _io ):
        self.Write( ":MOD " + str( _io ) ) 

        
    #------------------------------
    # Read Frequency
    #------------------------------
    def GetFrequency( self ):
        _freq = self.ras_smb_100a.ask(":FREQ?")
        return float( _freq )

    #------------------------------
    # Read Power
    #------------------------------
    def GetPower( self ):
        _pow = self.ras_smb_100a.ask(":POW?")
        return float( _pow )

    #------------------------------
    # Read I/O
    #------------------------------
    def GetIO( self ):
        _io = self.ras_smb_100a.ask(":OUTP?")
        return int(_io) 

    #------------------------------
    # Read Modulation Status
    #------------------------------
    def GetModulationIO( self ):
        _mod_io = self.ras_smb_100a.ask(":MOD?")
        return int(_mod_io) 



    
    #-------------------------------
    # Get Blind Status (Annotation)
    #     0 : Blind mode
    #     1 : Unblind mode
    #-------------------------------
    def GetBlindMode( self ):
        _mode = self.ras_smb_100a.ask( ":DISP:ANN:FREQ?" ) 
        return int( _mode )

#    #-----------------------------
#    # Read Capacitance
#    #-----------------------------
#    def ReadC( self ):
#        while True :
#            self.Write("ABOR;INIT")
#            _str = self.ras_smb_100a.ask("*TRG")
#            try :
#                # Can convert into float?
#                _strs = _str.split(",")
#                return (float(_strs[0]), float(_strs[1]))
#            except :
#                # Do re-read
#                continue

