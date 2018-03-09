#!/usr/bin/env python3.6
# -*- coding: utf-8 -*-
# Copyright : see accompanying license files for details

__author__  = "Damien Coupry"
__credits__ = ["Prof. Matthew Addicoat"]
__license__ = "MIT"
__maintainer__ = "Damien Coupry"
__version__ = 2.0
__status__  = "alpha"

import os
import sys
import numpy
import random
import ase
import scipy
import scipy.optimize


from autografs.utils.sbu        import read_sbu_database
from autografs.utils.sbu        import SBU
from autografs.utils.topologies import read_topologies_database
from autografs.utils.topologies import Topology
from autografs.utils.mmanalysis import analyze_mm 
from autografs.framework        import Framework



class Autografs(object):
    """Framework maker class to generate ASE Atoms objects from topologies.

    AuToGraFS: Automatic Topological Generator for Framework Structures.
    Addicoat, M. a, Coupry, D. E., & Heine, T. (2014).
    The Journal of Physical Chemistry. A, 118(40), 9607–14. 
    """

    def  __init__(self):
        """Constructor for the Autografs framework maker.
        """
        self.topologies : dict      = read_topologies_database()
        self.sbu        : ase.Atoms = read_sbu_database()

    def make(self,
             topology_name : str,
             sbu_names     : str  = None,
             sbu_dict      : dict = None) -> ase.Atoms :
        """Create a framework using given topology and sbu.

        Main funtion of Autografs. The sbu names and topology's
        are to be taken from the compiled databases. The sbu_dict
        can also be passed for multiple components frameworks.
        If the sbu_names is a list of tuples in the shape 
        (name,n), the number n will be used as a drawing probability
        when multiple options are available for the same shape.
        topology_name -- name of the topology to use
        sbu_names     -- list of names of the sbu to use
        sbu_dict -- (optional) one to one sbu to slot correspondance
                    in the shape {index of slot : 'name of sbu'}
        """
        topology = Topology(name  = topology_name,
                            atoms = self.topologies[topology_name])
        # container for the aligned SBUs
        aligned  = Framework()
        aligned.set_topology(topology=topology.get_atoms())
        alpha    = 0.0
        # identify the corresponding SBU
        if sbu_dict is None:
            sbu_dict = self.get_sbu_dict(topology=topology,
                                         sbu_names=sbu_names)
        # carry on
        for idx,sbu in sbu_dict.items():
            fragment_atoms = topology.fragments[idx]
            sbu_atoms      = sbu.atoms
            # check if has all info
            sbu_info    = list(sbu.atoms.info.keys())
            has_mmtypes = ("mmtypes" in sbu_info)
            has_bonds   = ("bonds"   in sbu_info)
            if has_bonds and has_mmtypes:
                sbu_types = sbu.atoms.info["mmtypes"]
                sbu_bonds = sbu.atoms.info["bonds"]
            else:
                sbu_bonds,sbu_types = analyze_mm(sbu.get_atoms())
            # align and get the scaling factor
            sbu_atoms,f = self.align(fragment=fragment_atoms,
                               sbu=sbu_atoms)
            alpha += f
            aligned.append(index=idx,sbu=sbu_atoms,mmtypes=sbu_types,bonds=sbu_bonds)
        # refine the cell scaling using a good starting point
        aligned.refine(alpha0=alpha)
        return aligned

    def get_sbu_dict(self,
                     topology  : dict,
                     sbu_names : list) -> dict:
        """Return a dictionary of SBU by corresponding fragment.

        This stage get a one to one correspondance between
        each topology slot and an available SBU from the list of names.
        TODO: For now, we take the first available if more are given,
        but we should be able to pass this directly to the class,
        or a dictionary of probabilities for the different SBU.
        We also need to implement a check on symmetry operators,
        to catch stuff like 'squares cannot fit in a rectangle slot'.
        topology  -- the Topology object
        sbu_names -- the list of SBU names as strings
        """
        from collections import defaultdict
        sbu_dict = {}
        for index,shape in topology.shapes.items():        
            by_shape = defaultdict(list)
            for name in sbu_names:
                sbu = SBU(name=name,atoms=self.sbu[name])
                by_shape[sbu.shape].append(sbu)
            # here, should accept probabilities also
            sbu_dict[index] = random.choice(by_shape[shape])
        return sbu_dict

    def align(self,
              fragment : ase.Atoms,
              sbu      : ase.Atoms) -> (ase.Atoms, float):
        """Return an aligned SBU.

        The SBU is rotated on top of the fragment
        using the procrustes library within scipy.
        a scaling factor is also calculated for all three
        cell vectors.
        fragment -- the slot in the topology, ASE Atoms
        sbu      -- object to align, ASE Atoms
        """
        # first, we work with copies
        sbu            =      sbu.copy()
        fragment       = fragment.copy()
        # normalize and center
        fragment_cop        = fragment.positions.mean(axis=0)
        fragment.positions -= fragment_cop
        sbu.positions      -= sbu.positions.mean(axis=0)
        # identify dummies in sbu
        sbu_Xis = [x.index for x in sbu if x.symbol=="X"]
        sbu_X   = sbu[sbu_Xis]
        # get the scaling factor
        size_sbu      = numpy.linalg.norm(sbu_X.positions,axis=1)
        size_fragment = numpy.linalg.norm(fragment.positions,axis=1)
        alpha         = 2.0 * numpy.mean(size_sbu/size_fragment)
        ncop          = numpy.linalg.norm(fragment_cop)
        if ncop<1e-6:
            direction  = numpy.ones(3,dtype=numpy.float32)
            direction /= numpy.linalg.norm(direction)
        else:
            direction = fragment_cop / ncop
        alpha *= direction
        # scaling for better alignment
        fragment.positions = fragment.positions.dot(numpy.eye(3)*alpha)
        # getting the rotation matrix
        X0  = sbu_X.get_positions()
        X1  = fragment.get_positions()
        R,s = scipy.linalg.orthogonal_procrustes(X0,X1)
        sbu.positions = sbu.positions.dot(R)
        # tag the atoms
        self.tag(sbu,fragment)
        return sbu,alpha

    def tag(self,
            sbu      : ase.Atoms,
            fragment : ase.Atoms) -> None:
        """Tranfer tags from the fragment to the closest dummies in the sbu"""
        for atom in sbu:
            if atom.symbol!="X":
                continue
            ps = atom.position
            pf = fragment.positions
            d  = numpy.linalg.norm(pf-ps,axis=1)
            fi = numpy.argmin(d)
            atom.tag = fragment[fi].tag
        return None

    def list_available_topologies(self,
                                  sbu  : list = [],
                                  full : bool = True) -> list:
        """Return a list of topologies compatible with the SBUs

        For each sbu in the list given in input, refines first by coordination
        then by shapes within the topology. Thus, we do not need to analyze
        every topology.
        sbu  -- list of sbu names
        full -- wether the topology is entirely represented by the sbu"""
        if sbu:
            topologies = []
            shapes = set([self.sbu[sbuk]["Shape"] for sbuk in sbu])
            for tk,tv in self.topologies.items():
                tcord = set(tk.get_atomic_numbers())
                if any(s[1] in tcord for s in shapes):
                    tv = Topology(name=tk,atoms=tv)
                    tshapes = tv.get_unique_shapes()
                    c0 = (all([s in tshapes for s in  shapes]))
                    c1 = (all([s in  shapes for s in tshapes]) and c0)
                    if c1 and full:
                        topologies.append(tk)
                    elif c0 and not full:
                        topologies.append(tk)
                else:
                    continue
        else:
            topologies = list(self.topologies.keys())
        return topologies

    def list_available_sbu(self,
                           topology : str) -> dict:
        """Return the dictionary of compatible SBU.
        
        Filters the existing SBU by shape until only
        those compatible with a slot within the topology are left.
        TODO: use the symmetry operators instead of the shape itself.
        topology -- name of the topology in the database
        """
        sbu = {shape:list(self.sbu.keys()) for shape in shapes}
        if topology:
            shapes = self.topologies[topology]["Shapes"]
            for shape in shapes:
                sbu[shape] = [sbuk for sbuk in sbu[shape] if self.sbu[sbuk]["Shape"]==shape]
        return sbu



if __name__ == "__main__":

    molgen         = Autografs()
    sbu_names      = ["Benzene_linear","Zn_mof5_octahedral"]
    topology_name  = "pcu"
    mof = molgen.make(topology_name=topology_name,sbu_names=sbu_names)
    ase.visualize.view(mof.get_atoms())

